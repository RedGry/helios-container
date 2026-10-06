"""Read-only Docker monitoring through the owner's existing guest SSH key."""
import json
import re
import shlex
import subprocess
import threading
import time

from runtime import Kit

LOG_LIMIT = 128 * 1024
FIELDS = ('ID', 'Names', 'Image', 'State', 'Status', 'Ports', 'CreatedAt')
PS_FORMAT = '{' + ','.join('"' + name + '":{{json .' + name + '}}' for name in FIELDS) + ',"protocol":{{json (.Label "helios-container.protocol")}},"polling":{{json (.Label "helios-container.polling")}}}'


class Dashboard:
    def __init__(self, base):
        self.base = base
        self.lock = threading.Lock()
        self.cached = None
        self.expires = 0

    def snapshot(self):
        # Coalesce browser polling. Do not start a stopped VM to inspect it.
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return self.cached
            kit = Kit(self.base)
            data = {'vm': {'running': bool(kit.pid()), 'cpus': kit.config['cpus'],
                           'memory_mib': kit.config['memory_mib']}, 'containers': [],
                    'updated_at': int(time.time()), 'error': None}
            if data['vm']['running']:
                command = shlex.join(['docker', 'container', 'ls', '-a', '--no-trunc', '--format', PS_FORMAT])
                command += " && printf '\\nHC_STATS\\n' && docker stats --no-stream --format '{{json .}}'"
                try:
                    result = subprocess.run(kit.ssh(command), capture_output=True, timeout=12, check=True)
                    listing, stats = result.stdout.decode('utf-8', 'replace').split('\nHC_STATS\n', 1)
                    usage = {row['ID']: row for row in map(json.loads, stats.splitlines()) if row}
                    for raw in listing.splitlines():
                        row = json.loads(raw)
                        row['protocol'] = row['protocol'] if row['protocol'] in ('http', 'https', 'tcp', 'udp') else 'unknown'
                        row['polling'] = row['polling'] if row['polling'] in ('true', 'false') else 'unknown'
                        metric = next((value for ident, value in usage.items() if row['ID'].startswith(ident)), {})
                        row['metrics'] = {key: metric.get(key) for key in ('CPUPerc', 'MemUsage', 'MemPerc', 'NetIO', 'BlockIO', 'PIDs')}
                        data['containers'].append(row)
                except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                    data['error'] = 'Docker пока не отвечает. VM может загружаться.'
            self.cached, self.expires = data, time.monotonic() + 5
            return data

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
