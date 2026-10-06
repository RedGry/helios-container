"""Per-user Docker inventory and bounded lifecycle actions through guest SSH."""
import json
import re
import secrets
import shlex
import subprocess
import threading
import time

from runtime import Kit

LOG_LIMIT = 128 * 1024
FIELDS = ('ID', 'Names', 'Image', 'State', 'Status', 'Ports', 'CreatedAt')
PS_FORMAT = '{' + ','.join('"' + name + '":{{json .' + name + '}}' for name in FIELDS) + ',"protocol":{{json (.Label "helios-container.protocol")}},"polling":{{json (.Label "helios-container.polling")}},"project":{{json (.Label "com.docker.compose.project")}},"service":{{json (.Label "com.docker.compose.service")}}}'
IMAGE_FORMAT = '{"ID":{{json .ID}},"Repository":{{json .Repository}},"Tag":{{json .Tag}},"CreatedAt":{{json .CreatedAt}},"Size":{{json .Size}}}'
VOLUME_FORMAT = '{"Name":{{json .Name}},"Driver":{{json .Driver}},"Scope":{{json .Scope}},"project":{{json (.Label "com.docker.compose.project")}}}'
MOUNT_FORMAT = '{"ID":{{json .Id}},"image_id":{{json .Image}},"started_at":{{json .State.StartedAt}},"mounts":{{json .Mounts}}}'
VOLUME_META_FORMAT = '{"Name":{{json .Name}},"CreatedAt":{{json .CreatedAt}}}'


def bytes_value(value):
    match = re.fullmatch(r'\s*([0-9.]+)\s*([A-Za-z]+)\s*', value)
    units = {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4,
             'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'TiB': 1024**4}
    if not match or match[2] not in units:
        return None
    return int(float(match[1]) * units[match[2]])


class Dashboard:
    def __init__(self, base):
        self.base = base
        self.lock = threading.Lock()
        self.cached = None
        self.expires = 0
        self.action_lock = threading.Lock()
        self.jobs = {}
        self.storage_lock = threading.Lock()
        self.storage_data = {'volumes': {}, 'images': {}, 'updated_at': None, 'error': None}
        self.storage_due = 0
        self.storage_running = False
        self.cpu_sample = None
        self.refreshing = False

    def snapshot(self):
        # Never hold the response path behind slow guest SSH or docker stats.
        with self.lock:
            if self.cached is None:
                kit = Kit(self.base)
                marker = self.base / 'VERSION'
                self.cached = {'vm': {'running': bool(kit.pid()), 'cpus': kit.config['cpus'],
                    'memory_mib': kit.config['memory_mib'], 'docker_running': None},
                    'containers': [], 'images': [], 'volumes': [], 'error': None,
                    'kit_version': marker.read_text().strip()[:40] if marker.is_file() else 'dev',
                    'updated_at': None, 'loading': True}
            if not self.refreshing and time.monotonic() >= self.expires:
                self.refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
            data = dict(self.cached, refreshing=self.refreshing)
        return self._with_storage(data)

    def _refresh(self):
        try:
            if self.cached.get('loading'):
                self._quick_collect()
            data = self._collect()
            if data['vm']['running'] and not data['error']:
                self._metrics_collect()
        except Exception:
            # Preserve the last usable inventory and make failed refresh observable.
            with self.lock:
                self.cached = dict(self.cached, error='Не удалось обновить данные. Повторная проверка через 10 секунд.')
                self.expires = time.monotonic() + 10
        finally:
            with self.lock:
                self.refreshing = False

    def _quick_collect(self):
        kit = Kit(self.base)
        if not kit.pid():
            return
        result = subprocess.run(kit.ssh(shlex.join(['docker', 'container', 'ls', '-a', '--no-trunc', '--format', PS_FORMAT])), capture_output=True, timeout=10, check=True)
        containers = []
        for raw in result.stdout.decode().splitlines():
            if not raw:
                continue
            row = json.loads(raw)
            row['protocol'] = row['protocol'] if row['protocol'] in ('http', 'https', 'tcp', 'udp') else 'unknown'
            row['polling'] = row['polling'] if row['polling'] in ('true', 'false') else 'unknown'
            row.update(metrics={key: None for key in ('CPUPerc', 'MemUsage', 'MemPerc', 'NetIO', 'BlockIO', 'PIDs')}, mounts=[], image_id='', started_at='')
            containers.append(row)
        with self.lock:
            self.cached = dict(self.cached, containers=containers, loading=False, inventory_pending=True, metrics_ready=False, updated_at=int(time.time()))

    def _collect(self):
        kit = Kit(self.base)
        data = {'vm': {'running': bool(kit.pid()), 'cpus': kit.config['cpus'],
                       'memory_mib': kit.config['memory_mib']}, 'containers': [], 'images': [], 'volumes': [],
                'updated_at': int(time.time()), 'error': None, 'metrics_ready': False}
        marker = self.base / 'VERSION'
        data['kit_version'] = marker.read_text().strip()[:40] if marker.is_file() else 'dev'
        data['vm'].update(cpu_percent=None, memory_used_bytes=None, disk_used_bytes=None, disk_total_bytes=None, docker_version=None, docker_running=False)
        if data['vm']['running']:
            command = shlex.join(['docker', 'container', 'ls', '-a', '--no-trunc', '--format', PS_FORMAT])
            command += " && printf '\\nHC_IMAGES\\n' && " + shlex.join(['docker', 'image', 'ls', '--all', '--no-trunc', '--format', IMAGE_FORMAT])
            command += " && printf '\\nHC_VOLUMES\\n' && " + shlex.join(['docker', 'volume', 'ls', '--format', VOLUME_FORMAT])
            command += " && printf '\\nHC_MOUNTS\\n' && docker container ls -aq | xargs -r " + shlex.join(['docker', 'inspect', '--format', MOUNT_FORMAT])
            command += " && printf '\\nHC_STATS\\n'"
            command += " && printf '\\nHC_MEMORY\\n' && awk '/MemTotal:/ {print $2}' /proc/meminfo"
            command += " && printf '\\nHC_VERSION\\n' && docker info --format '{{.ServerVersion}}'"
            command = "printf 'HC_HEALTH\\n'; awk '/MemTotal:/ {t=$2} /MemAvailable:/ {a=$2} END {print t; print a}' /proc/meminfo; head -n 1 /proc/stat; df -k /var/lib/docker | tail -n 1; printf '\\nHC_INVENTORY\\n'; " + command
            try:
                result = subprocess.run(kit.ssh(command), capture_output=True, timeout=15, check=False)
                raw = result.stdout.decode('utf-8', 'replace')
                if raw.startswith('HC_HEALTH\n'):
                    health, raw = raw.split('\nHC_INVENTORY\n', 1)
                    lines = health.splitlines()[1:]
                    data['vm']['memory_total_bytes'] = int(lines[0]) * 1024
                    data['vm']['memory_used_bytes'] = max(0, (int(lines[0]) - int(lines[1])) * 1024)
                    ticks = [int(v) for v in lines[2].split()[1:9]]
                    sample = (sum(ticks), ticks[3] + ticks[4])
                    if self.cpu_sample and sample[0] > self.cpu_sample[0]:
                        data['vm']['cpu_percent'] = round(100 * (1 - (sample[1] - self.cpu_sample[1]) / (sample[0] - self.cpu_sample[0])), 2)
                    self.cpu_sample = sample
                    disk = lines[3].split()
                    data['vm'].update(disk_total_bytes=int(disk[1])*1024, disk_used_bytes=int(disk[2])*1024)
                listing, rest = raw.split('\nHC_IMAGES\n', 1)
                images, rest = rest.split('\nHC_VOLUMES\n', 1)
                volumes, rest = rest.split('\nHC_MOUNTS\n', 1)
                mounts, stats = rest.split('\nHC_STATS\n', 1)
                stats, memory = stats.split('\nHC_MEMORY\n', 1)
                if '\nHC_VERSION\n' in memory:
                    memory, version = memory.split('\nHC_VERSION\n', 1)
                    data['vm']['docker_version'] = version.strip()[:40]
                data['vm']['docker_running'] = True
                data['vm']['memory_total_bytes'] = int(memory.strip()) * 1024
                details = {row['ID']: row for row in map(json.loads, mounts.splitlines()) if row}
                usage = {row['ID']: row for row in map(json.loads, stats.splitlines()) if row}
                with self.lock:
                    previous = self.cached or {}
                    old_usage = {c['ID']: c['metrics'] for c in previous.get('containers', [])}
                    data['metrics_ready'] = bool(usage) or previous.get('metrics_ready', False)
                    data['metrics_updated_at'] = previous.get('metrics_updated_at')
                for raw in listing.splitlines():
                    row = json.loads(raw)
                    row['protocol'] = row['protocol'] if row['protocol'] in ('http', 'https', 'tcp', 'udp') else 'unknown'
                    row['polling'] = row['polling'] if row['polling'] in ('true', 'false') else 'unknown'
                    metric = next((value for ident, value in usage.items() if row['ID'].startswith(ident)), old_usage.get(row['ID'], {}))
                    row['metrics'] = {key: metric.get(key) for key in ('CPUPerc', 'MemUsage', 'MemPerc', 'NetIO', 'BlockIO', 'PIDs')}
                    detail = details.get(row['ID'], {})
                    row['image_id'] = detail.get('image_id', '')
                    row['started_at'] = detail.get('started_at', '')
                    row['mounts'] = [{key: mount.get(key) for key in ('Type', 'Name', 'Destination', 'RW')} for mount in detail.get('mounts', [])]
                    data['containers'].append(row)
                data['images'] = [json.loads(row) for row in images.splitlines() if row]
                data['volumes'] = [json.loads(row) for row in volumes.splitlines() if row]
                for image in data['images']:
                    image['containers'] = [c['Names'] for c in data['containers'] if c['image_id'] == image['ID']]
                for volume in data['volumes']:
                    volume['containers'] = [c['Names'] for c in data['containers'] if any(m['Type'] == 'volume' and m['Name'] == volume['Name'] for m in c['mounts'])]
            except (subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError):
                data['error'] = 'Docker пока не отвечает. VM может загружаться.'
        with self.lock:
            self.cached, self.expires = data, time.monotonic() + 10
        return self._with_storage(data)

    def _metrics_collect(self):
        kit = Kit(self.base)
        if not kit.pid():
            return
        try:
            result = subprocess.run(kit.ssh("docker stats --no-stream --format '{{json .}}'"), capture_output=True, timeout=15, check=True)
            usage = [json.loads(line) for line in result.stdout.decode().splitlines() if line]
            with self.lock:
                data = dict(self.cached)
                data['containers'] = [dict(c) for c in data['containers']]
                for container in data['containers']:
                    metric = next((m for m in usage if container['ID'].startswith(m['ID'])), {})
                    container['metrics'] = {key: metric.get(key) for key in ('CPUPerc', 'MemUsage', 'MemPerc', 'NetIO', 'BlockIO', 'PIDs')}
                data['metrics_ready'] = True
                data['metrics_updated_at'] = int(time.time())
                self.cached = data
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            with self.lock:
                self.cached = dict(self.cached, metrics_error='Статистика пока недоступна. Список контейнеров загружен.')

    def _with_storage(self, data):
        with self.storage_lock:
            storage = self.storage_data
            data['storage'] = {'updated_at': storage['updated_at'], 'error': storage['error'], 'pending': self.storage_running}
            for volume in data['volumes']:
                volume.update(storage['volumes'].get(volume['Name'], {'Size': None, 'size_bytes': None, 'CreatedAt': None}))
            for image in data['images']:
                image.update(storage['images'].get(image['ID'], {}))
                image['size_bytes'] = bytes_value(image['Size'])
            missing = any(v['Name'] not in storage['volumes'] for v in data['volumes'])
            if data['vm']['running'] and not data.get('loading') and not data.get('inventory_pending') and not data.get('error') and not self.storage_running and (time.monotonic() >= self.storage_due or missing and not storage['error']):
                self.storage_running = True
                data['storage']['pending'] = True
                threading.Thread(target=self._storage_update, daemon=True).start()
        data['resources'] = {
            'cpu_percent': round(sum(float(c['metrics']['CPUPerc'].rstrip('%')) for c in data['containers'] if c['metrics']['CPUPerc']), 2),
            'cpu_capacity_percent': data['vm']['cpus'] * 100,
            'memory_used_bytes': sum(bytes_value(c['metrics']['MemUsage'].split('/')[0]) or 0 for c in data['containers'] if c['metrics']['MemUsage']),
            'memory_total_bytes': data['vm'].get('memory_total_bytes', data['vm']['memory_mib'] * 1024**2)}
        return data

    def _storage_update(self):
        try:
            kit = Kit(self.base)
            if not kit.pid():
                raise RuntimeError('VM stopped')
            command = "docker system df --verbose --format '{{json .}}' && printf '\\nHC_VOLUME_META\\n' && docker volume ls -q | xargs -r " + shlex.join(['docker', 'volume', 'inspect', '--format', VOLUME_META_FORMAT])
            result = subprocess.run(kit.ssh(command), capture_output=True, timeout=45, check=True)
            raw, metadata = result.stdout.decode('utf-8', 'replace').split('\nHC_VOLUME_META\n', 1)
            disk = json.loads(raw)
            dates = {v['Name']: v.get('CreatedAt') for v in map(json.loads, metadata.splitlines()) if v}
            volumes = {v['Name']: {'Size': v.get('Size'), 'size_bytes': bytes_value(v.get('Size') or ''), 'CreatedAt': dates.get(v['Name'])} for v in disk.get('Volumes', [])}
            images = {i['ID']: {key: i.get(key) for key in ('SharedSize', 'UniqueSize')} for i in disk.get('Images', [])}
            value = {'volumes': volumes, 'images': images, 'updated_at': int(time.time()), 'error': None}
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            value = dict(self.storage_data, error='Размеры пока недоступны. Повторная проверка через минуту.')
        with self.storage_lock:
            self.storage_data = value
            self.storage_due = time.monotonic() + 60
            self.storage_running = False

    def action(self, payload):
        if not isinstance(payload, dict) or payload.get('action') not in ('start', 'stop', 'restart', 'delete'):
            raise ValueError('Недопустимая операция.')
        kind, target = payload.get('kind', 'container'), payload.get('id', '')
        if kind in ('vm', 'engine'):
            if target != kind or payload['action'] not in ('start', 'stop'):
                raise ValueError('Недопустимая операция VM или Docker.')
            if payload['action'] == 'stop' and payload.get('confirm') != kind:
                raise ValueError('Подтвердите остановку приложений.')
            if kind == 'engine' and not Kit(self.base).pid():
                raise ValueError('Сначала запустите VM.')
            return self._queue([], payload['action'], kind)
        if kind not in ('container', 'project', 'image', 'volume') or not isinstance(target, str) or not target or len(target) > 200:
            raise ValueError('Некорректный контейнер или проект.')
        if kind == 'container' and not re.fullmatch(r'[0-9a-f]{12,64}', target):
            raise ValueError('Некорректный ID контейнера.')
        snapshot = self.snapshot()
        if snapshot.get('loading'):
            raise ValueError('Дождитесь загрузки списка контейнеров.')
        if not snapshot['vm']['running'] or snapshot['error']:
            raise ValueError('Docker недоступен. Сначала запустите VM.')
        if kind in ('container', 'project'):
            ids = [c['ID'] for c in snapshot['containers'] if (c.get('project') == target if kind == 'project' else c['ID'] == target)]
            if not ids or any(not re.fullmatch(r'[0-9a-f]{64}', ident) for ident in ids):
                raise ValueError('Контейнер или проект больше не существует. Обновите список.')
            if payload['action'] == 'delete':
                containers = [c for c in snapshot['containers'] if c['ID'] in ids]
                if any(c['State'] not in ('exited', 'created', 'dead') for c in containers):
                    raise ValueError('Сначала остановите все выбранные контейнеры.')
                confirmation = target if kind == 'project' else containers[0]['Names']
                if payload.get('confirm') != confirmation:
                    raise ValueError('Подтвердите удаление выбранного объекта.')
                if kind == 'project' and payload.get('container_ids') != sorted(ids):
                    raise ValueError('Состав проекта изменился. Обновите список и подтвердите удаление снова.')
        else:
            if payload['action'] != 'delete':
                raise ValueError('Для образов и volumes доступно только удаление.')
            if kind == 'image':
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', target):
                    raise ValueError('Некорректный ID образа.')
                image = next((i for i in snapshot['images'] if i['ID'] == target and self.image_reference(i) == payload.get('reference')), None)
                if not image:
                    raise ValueError('Образ больше не существует. Обновите каталог.')
                if image['containers']:
                    raise ValueError('Образ используется контейнерами, включая остановленные.')
                confirmation = self.image_reference(image)
            else:
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', target):
                    raise ValueError('Некорректное имя volume.')
                volume = next((v for v in snapshot['volumes'] if v['Name'] == target), None)
                if not volume:
                    raise ValueError('Volume больше не существует. Обновите каталог.')
                if volume['containers']:
                    raise ValueError('Volume используется контейнерами, включая остановленные.')
                confirmation = target
            if payload.get('confirm') != confirmation:
                raise ValueError('Подтвердите удаление выбранного объекта.')
            ids = [confirmation]
        return self._queue(ids, payload['action'], kind, target if kind == 'image' else None)

    def _queue(self, ids, action, kind, expected_image=None):
        with self.action_lock:
            if any(job['status'] == 'running' for job in self.jobs.values()):
                raise ValueError('Дождитесь завершения текущей операции.')
            self.jobs = dict(list(self.jobs.items())[-15:])
            token = secrets.token_hex(16)
            job = {'id': token, 'action': action, 'status': 'running', 'error': None}
            self.jobs[token] = job
            threading.Thread(target=self._perform, args=(token, ids, action, kind, expected_image), daemon=True).start()
            return dict(job)

    @staticmethod
    def image_reference(image):
        return image['ID'] if '<none>' in (image['Repository'], image['Tag']) else image['Repository'] + ':' + image['Tag']

    def _perform(self, token, ids, action, kind='container', expected_image=None):
        error = None
        try:
            kit = Kit(self.base)
            if kind == 'vm':
                if action == 'start':
                    kit.start(wait=False)
                else:
                    kit.stop()
            elif kind == 'engine':
                if not kit.pid():
                    raise RuntimeError('VM stopped')
                subprocess.run(kit.ssh('rc-service docker ' + action), capture_output=True, timeout=120, check=True)
            else:
                self._container_operation(kit, ids, action, kind, expected_image)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            error = 'Операция не завершилась. Обновите состояние VM и Docker.'
        with self.action_lock:
            self.jobs[token].update(status='error' if error else 'done', error=error)
        with self.lock:
            self.expires = 0
        with self.storage_lock:
            self.storage_due = 0

    def _container_operation(self, kit, ids, action, kind, expected_image):
            if not kit.pid():
                raise RuntimeError('VM stopped')
            arguments = (['docker', 'container' if kind == 'project' else kind, 'rm', '--'] + ids if action == 'delete' else
                         ['docker', action] + (['--time', '5'] if action in ('stop', 'restart') else []) + ids)
            # Runtime activity lease also protects an action from optional idle shutdown.
            try:
                from idle import activity
            except ImportError:
                from contextlib import nullcontext
                activity = lambda kit: nullcontext()
            with activity(kit):
                if action == 'delete' and kind == 'image':
                    current = subprocess.run(kit.ssh(shlex.join(['docker', 'image', 'inspect', '--format', '{{.Id}}', ids[0]])), capture_output=True, timeout=10, check=True)
                    if current.stdout.decode().strip() != expected_image:
                        raise RuntimeError('Image reference changed')
                subprocess.run(kit.ssh(shlex.join(arguments)), capture_output=True, timeout=90, check=True)

    def job(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
            raise ValueError('Некорректный ID операции.')
        with self.action_lock:
            if token not in self.jobs:
                raise ValueError('Операция не найдена. Обновите состояние контейнеров.')
            return dict(self.jobs[token])

    def logs(self, ident, tail):
        if not re.fullmatch(r'[0-9a-f]{12,64}', ident) or not re.fullmatch(r'[0-9]{1,4}', tail) or not 1 <= int(tail) <= 1000:
            raise ValueError('Укажите ID контейнера и от 1 до 1000 строк.')
        kit = Kit(self.base)
        if not kit.pid():
            raise ValueError('VM остановлена.')
        # Only hexadecimal IDs can enter this shell command. Bound bytes in the guest,
        # including stderr, before transmitting them over SSH. No follow/exec API.
        command = shlex.join(['docker', 'logs', '--timestamps', '--tail', tail, ident])
        command += ' 2>&1 | tail -c ' + str(LOG_LIMIT + 1)
        result = subprocess.run(kit.ssh(command), capture_output=True, timeout=8, check=True)
        raw = result.stdout
        return {'id': ident, 'text': raw[-LOG_LIMIT:].decode('utf-8', 'replace'),
                'truncated': len(raw) > LOG_LIMIT, 'tail': int(tail)}
