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

    def snapshot(self):
        # Coalesce browser polling. Do not start a stopped VM to inspect it.
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return self._with_storage(self.cached)
            kit = Kit(self.base)
            data = {'vm': {'running': bool(kit.pid()), 'cpus': kit.config['cpus'],
                           'memory_mib': kit.config['memory_mib']}, 'containers': [], 'images': [], 'volumes': [],
                    'updated_at': int(time.time()), 'error': None}
            if data['vm']['running']:
                command = shlex.join(['docker', 'container', 'ls', '-a', '--no-trunc', '--format', PS_FORMAT])
                command += " && printf '\\nHC_IMAGES\\n' && " + shlex.join(['docker', 'image', 'ls', '--all', '--no-trunc', '--format', IMAGE_FORMAT])
                command += " && printf '\\nHC_VOLUMES\\n' && " + shlex.join(['docker', 'volume', 'ls', '--format', VOLUME_FORMAT])
                command += " && printf '\\nHC_MOUNTS\\n' && docker container ls -aq | xargs -r " + shlex.join(['docker', 'inspect', '--format', MOUNT_FORMAT])
                command += " && printf '\\nHC_STATS\\n' && docker stats --no-stream --format '{{json .}}'"
                command += " && printf '\\nHC_MEMORY\\n' && awk '/MemTotal:/ {print $2}' /proc/meminfo"
                try:
                    result = subprocess.run(kit.ssh(command), capture_output=True, timeout=15, check=True)
                    listing, rest = result.stdout.decode('utf-8', 'replace').split('\nHC_IMAGES\n', 1)
                    images, rest = rest.split('\nHC_VOLUMES\n', 1)
                    volumes, rest = rest.split('\nHC_MOUNTS\n', 1)
                    mounts, stats = rest.split('\nHC_STATS\n', 1)
                    stats, memory = stats.split('\nHC_MEMORY\n', 1)
                    data['vm']['memory_total_bytes'] = int(memory.strip()) * 1024
                    details = {row['ID']: row for row in map(json.loads, mounts.splitlines()) if row}
                    usage = {row['ID']: row for row in map(json.loads, stats.splitlines()) if row}
                    for raw in listing.splitlines():
                        row = json.loads(raw)
                        row['protocol'] = row['protocol'] if row['protocol'] in ('http', 'https', 'tcp', 'udp') else 'unknown'
                        row['polling'] = row['polling'] if row['polling'] in ('true', 'false') else 'unknown'
                        metric = next((value for ident, value in usage.items() if row['ID'].startswith(ident)), {})
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
                except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                    data['error'] = 'Docker пока не отвечает. VM может загружаться.'
            self.cached, self.expires = data, time.monotonic() + 5
            return self._with_storage(data)

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
            if data['vm']['running'] and not self.storage_running and (time.monotonic() >= self.storage_due or missing and not storage['error']):
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
        if kind not in ('container', 'project', 'image', 'volume') or not isinstance(target, str) or not target or len(target) > 200:
            raise ValueError('Некорректный контейнер или проект.')
        if kind == 'container' and not re.fullmatch(r'[0-9a-f]{12,64}', target):
            raise ValueError('Некорректный ID контейнера.')
        snapshot = self.snapshot()
        if not snapshot['vm']['running'] or snapshot['error']:
            raise ValueError('Docker недоступен. Сначала запустите VM.')
        if kind in ('container', 'project'):
            if payload['action'] == 'delete':
                raise ValueError('Удаление контейнеров и проектов не поддерживается.')
            ids = [c['ID'] for c in snapshot['containers'] if (c.get('project') == target if kind == 'project' else c['ID'] == target)]
            if not ids or any(not re.fullmatch(r'[0-9a-f]{64}', ident) for ident in ids):
                raise ValueError('Контейнер или проект больше не существует. Обновите список.')
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
        with self.action_lock:
            if any(job['status'] == 'running' for job in self.jobs.values()):
                raise ValueError('Дождитесь завершения текущей операции.')
            self.jobs = dict(list(self.jobs.items())[-15:])
            token = secrets.token_hex(16)
            job = {'id': token, 'action': payload['action'], 'status': 'running', 'error': None}
            self.jobs[token] = job
            threading.Thread(target=self._perform, args=(token, ids, payload['action'], kind, target if kind == 'image' else None), daemon=True).start()
            return dict(job)

    @staticmethod
    def image_reference(image):
        return image['ID'] if '<none>' in (image['Repository'], image['Tag']) else image['Repository'] + ':' + image['Tag']

    def _perform(self, token, ids, action, kind='container', expected_image=None):
        error = None
        try:
            kit = Kit(self.base)
            if not kit.pid():
                raise RuntimeError('VM stopped')
            arguments = (['docker', kind, 'rm', '--'] + ids if action == 'delete' else
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
        except (OSError, RuntimeError, subprocess.SubprocessError):
            error = 'Docker не завершил операцию. Обновите состояние контейнеров.'
        with self.action_lock:
            self.jobs[token].update(status='error' if error else 'done', error=error)
        with self.lock:
            self.expires = 0
        with self.storage_lock:
            self.storage_due = 0

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
