#!/usr/bin/env python3
"""Optional per-user HTTP bridge for PHP userdir hosting. No dependencies."""
import argparse
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from runtime import Kit, free_port
from dashboard import Dashboard

MAX_BODY = 8 * 1024**2
MAX_RESPONSE = 16 * 1024**2
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}
MARKER = '// helios-container managed web gateway'


def parse_ports(text):
    result = []
    for item in re.split(r'[\s,;]+', text.strip()):
        if not item:
            continue
        match = re.fullmatch(r'(host:)?([0-9]{1,5})', item)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError('Введите порты: 8080, 8081, host:3000.')
        kind, port = ('host' if match[1] else 'vm'), int(match[2])
        if kind == 'host' and port < 1024:
            raise ValueError('Порт backend на helios должен быть не ниже 1024.')
        route = {'kind': kind, 'port': port}
        if route not in result:
            result.append(route)
    if len(result) > 8:
        raise ValueError('Можно опубликовать до 8 портов.')
    return result


def owned_listener(port):
    user = username()
    output = subprocess.check_output(['sockstat', '-4', '-l', '-P', 'tcp'], text=True)
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 6 and fields[0] == user and fields[5] in (f'127.0.0.1:{port}', f'*:{port}', f'0.0.0.0:{port}'):
            return True
    return False


def username():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def save(base, state):
    temporary = base / 'web.json.tmp'
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(base / 'web.json')


def load(base):
    return json.loads((base / 'web.json').read_text())


def agent_pid(base):
    try:
        pid = int((base / 'web.pid').read_text())
        uid, command = subprocess.check_output(['ps', '-ww', '-p', str(pid), '-o', 'uid=', '-o', 'command='], text=True).strip().split(None, 1)
        if int(uid) == os.getuid() and str(base / 'gateway.py') in command and 'serve' in command:
            return pid
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def ensure_agent(base):
    state = load(base)
    if not agent_pid(base):
        with (base / 'web.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(base / 'gateway.py'), 'serve', '--base', str(base)],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        (base / 'web.pid').write_text(str(process.pid))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{state["agent_port"]}/_health', headers={'X-HC-Bridge': state['bridge_key']})
            with urllib.request.urlopen(request, timeout=1) as response:
                if response.read() == b'helios-container gateway':
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(.2)
    raise RuntimeError('Шлюз не запустился. Проверьте web.log в каталоге kit и helios-container web start.')


def stop_agent(base):
    pid = agent_pid(base)
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not agent_pid(base):
                break
            time.sleep(.1)


def manage(kit, argv):
    parser = argparse.ArgumentParser(prog='helios-container web')
    parser.add_argument('action', choices=['install', 'info', 'start', 'stop', 'remove'])
    args = parser.parse_args(argv)
    base = kit.base
    if args.action == 'install':
        public = Path.home() / 'public_html'
        root = public / 'helios-container'
        if public.is_symlink() or root.is_symlink():
            raise RuntimeError('public_html и каталог шлюза не должны быть ссылками.')
        if (base / 'web.json').exists():
            state = load(base)
        else:
            if root.exists() and any(root.iterdir()):
                raise RuntimeError('public_html/helios-container уже занят. Существующие файлы сохранены.')
            public.mkdir(mode=0o755, exist_ok=True)
            root.mkdir(mode=0o755, exist_ok=True)
            nonce = secrets.token_hex(16)
            probe = root / ('probe-' + nonce + '.php')
            probe.write_text('<?php echo ' + repr(nonce) + ';')
            probe.chmod(0o644)
            url = 'https://se.ifmo.ru/~' + urllib.parse.quote(username()) + '/helios-container/'
            try:
                with urllib.request.urlopen(url + probe.name, timeout=20) as response:
                    if response.read() != nonce.encode():
                        raise RuntimeError('Хостинг не выполняет PHP. Шлюз не установлен.')
            finally:
                probe.unlink(missing_ok=True)
            state = {'url': url, 'directory': str(root), 'agent_port': free_port(),
                     'admin_key': secrets.token_hex(32), 'bridge_key': secrets.token_hex(32), 'routes': []}
            save(base, state)
        index = root / 'index.php'
        if index.is_symlink() or (index.exists() and MARKER not in index.read_text()):
            raise RuntimeError('index.php уже существует и не принадлежит kit.')
        access = root / '.htaccess'
        access_marker = '# helios-container managed web methods'
        if access.is_symlink() or (access.exists() and access_marker not in access.read_text()):
            raise RuntimeError('.htaccess уже существует и не принадлежит kit.')
        template = (base / 'gateway.php').read_text()
        index.write_text(template.replace('__HC_PORT__', str(state['agent_port'])).replace('__HC_BRIDGE__', state['bridge_key']))
        index.chmod(0o644)
        access.write_text((base / 'gateway.htaccess').read_text())
        access.chmod(0o644)
        ensure_agent(base)
    elif args.action == 'start':
        ensure_agent(base)
    elif args.action == 'stop':
        stop_agent(base)
        return 0
    elif args.action == 'remove':
        state = load(base)
        root = Path(state['directory'])
        expected = Path.home() / 'public_html/helios-container'
        if root != expected or root.is_symlink():
            raise RuntimeError('Отказ удаления: неизвестный каталог шлюза.')
        index = root / 'index.php'
        if index.is_symlink() or (index.exists() and MARKER not in index.read_text()):
            raise RuntimeError('Отказ удаления: index.php не принадлежит kit.')
        access = root / '.htaccess'
        if access.is_symlink() or (access.exists() and '# helios-container managed web methods' not in access.read_text()):
            raise RuntimeError('Отказ удаления: .htaccess не принадлежит kit.')
        stop_agent(base)
        index.unlink(missing_ok=True)
        access.unlink(missing_ok=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
        for name in ('web.json', 'web.pid', 'web.log'):
            (base / name).unlink(missing_ok=True)
        print('HTTP-шлюз удалён. Frontend и VM сохранены.')
        return 0
    state = load(base)
    print('Страница: ' + state['url'])
    print('Управление (приватная ссылка): ' + state['url'] + '#key=' + state['admin_key'])
    print('Агент: ' + ('работает' if agent_pid(base) else 'остановлен'))
    return 0


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, base):
        self.base = base
        self.state = load(base)
        self.config_lock = threading.Lock()
        self.dashboard = Dashboard(base)
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(('127.0.0.1', self.state['agent_port']), Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def reply(self, code, data, headers=(), content_length=None):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(data) if content_length is None else content_length))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def json_reply(self, code, value):
        self.reply(code, json.dumps(value, ensure_ascii=False).encode(), [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store')])

    def handle_request(self):
        state = self.server.state
        if not hmac.compare_digest(self.headers.get('X-HC-Bridge', ''), state['bridge_key']):
            self.json_reply(403, {'error': 'Нет доступа к шлюзу.'}); return
        if self.path == '/_health' and self.command == 'GET':
            self.reply(200, b'helios-container gateway'); return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in ('/_dashboard', '/_logs', '/_action'):
            if not hmac.compare_digest(self.headers.get('X-HC-Admin', ''), state['admin_key']):
                self.json_reply(401, {'error': 'Откройте приватную ссылку из helios-container web info.'}); return
            if parsed.path == '/_action':
                if self.command == 'POST':
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096:
                        self.json_reply(413, {'error': 'Слишком большой запрос.'}); return
                    self.json_reply(202, self.server.dashboard.action(json.loads(self.rfile.read(length))))
                elif self.command == 'GET':
                    query = urllib.parse.parse_qs(parsed.query)
                    self.json_reply(200, self.server.dashboard.job(query.get('id', [''])[0]))
                else:
                    self.json_reply(405, {'error': 'Используйте GET или POST.'})
                return
            if self.command != 'GET':
                self.json_reply(405, {'error': 'Панель доступна только для чтения.'}); return
            if parsed.path == '/_logs':
                query = urllib.parse.parse_qs(parsed.query)
                data = self.server.dashboard.logs(query.get('id', [''])[0], query.get('tail', ['200'])[0])
            else:
                data = dict(self.server.dashboard.snapshot())
                data['routes'] = [{'kind': r['kind'], 'port': r['port'],
                                   'path': f'/{r["kind"]}/{r["port"]}/',
                                   'listening': owned_listener(r['target'])} for r in list(state['routes'])]
            self.json_reply(200, data); return
        if self.path == '/_config':
            if not hmac.compare_digest(self.headers.get('X-HC-Admin', ''), state['admin_key']):
                self.json_reply(401, {'error': 'Откройте приватную ссылку из helios-container web info.'}); return
            if self.command == 'POST':
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    self.json_reply(413, {'error': 'Слишком большой запрос.'}); return
                parsed = json.loads(self.rfile.read(length))
                routes = parse_ports(parsed['ports'])
                with self.server.config_lock:
                    kit = Kit(self.server.base)
                    if any(r['kind'] == 'vm' for r in routes) and not kit.pid():
                        raise ValueError('VM остановлена. Сначала выполните helios-container start.')
                    for route in routes:
                        if route['kind'] == 'host':
                            if not owned_listener(route['port']):
                                raise ValueError(f'Порт {route["port"]} не слушает процесс вашего пользователя на helios.')
                            route['target'] = route['port']
                        else:
                            route['target'] = kit.forward(route['port'])
                    state['routes'] = routes
                    save(self.server.base, state)
            elif self.command != 'GET':
                self.json_reply(405, {'error': 'Используйте GET или POST.'}); return
            self.json_reply(200, {'ports': ', '.join(('host:' if r['kind'] == 'host' else '') + str(r['port']) for r in state['routes']),
                                  'routes': [{'port': r['port'], 'kind': r['kind'], 'path': f'/{r["kind"]}/{r["port"]}/'} for r in state['routes']]})
            return
        parsed = urllib.parse.urlsplit(self.path)
        match = re.fullmatch(r'/(vm|host)/([0-9]{1,5})(/.*)?', parsed.path)
        route = next((r for r in state['routes'] if match and r['kind'] == match[1] and r['port'] == int(match[2])), None)
        if not route:
            self.json_reply(404, {'error': 'Порт не опубликован.'}); return
        if route['kind'] == 'host' and not owned_listener(route['port']):
            self.json_reply(503, {'error': 'Backend не запущен вашим пользователем.'}); return
        if route['kind'] == 'vm':
            kit = Kit(self.server.base)
            mapping = next((r for r in kit.config.get('forwards', []) if r['guest'] == route['port']), None)
            if not kit.pid() or not mapping or mapping['host'] != route['target']:
                self.json_reply(503, {'error': 'VM остановлена или проброс изменён. Запустите VM и сохраните порты в форме.'}); return
        if self.command not in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
            self.json_reply(405, {'error': 'HTTP-метод не поддерживается.'}); return
        if self.headers.get('Transfer-Encoding'):
            self.json_reply(400, {'error': 'Chunked-загрузка не поддерживается.'}); return
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 <= length <= MAX_BODY:
            self.json_reply(413, {'error': 'Тело запроса больше 8 МиБ.'}); return
        body = self.rfile.read(length)
        if len(body) != length:
            self.json_reply(400, {'error': 'Неполное тело запроса.'}); return
        path = match[3] or '/'
        if parsed.query:
            path += '?' + parsed.query
        removed = HOP | {'host', 'expect'} | {v.strip().lower() for v in self.headers.get('Connection', '').split(',')}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in removed and not k.lower().startswith(('x-hc-', 'x-forwarded-'))}
        prefix = self.headers.get('X-HC-Prefix', '') + f'/{route["kind"]}/{route["port"]}'
        headers.update({'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'se.ifmo.ru', 'X-Forwarded-Prefix': prefix})
        connection = http.client.HTTPConnection('127.0.0.1', route['target'], timeout=15)
        try:
            connection.request(self.command, path, body, headers)
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                self.json_reply(502, {'error': 'Ответ backend больше 16 МиБ.'}); return
            excluded = HOP | {v.strip().lower() for v in response.getheader('Connection', '').split(',')}
            outgoing = []
            for key, value in response.getheaders():
                if key.lower() in excluded:
                    continue
                if key.lower() == 'location':
                    local = f'http://127.0.0.1:{route["target"]}'
                    if value.startswith(local + '/'):
                        value = value[len(local):]
                    if value.startswith('/') and not value.startswith('//'):
                        value = prefix + value
                elif key.lower() == 'set-cookie':
                    value = re.sub(r';\s*Domain=[^;]*', '', value, flags=re.I)
                    value = re.sub(r'(;\s*Path=)(/[^;]*)', lambda m: m[1] + prefix + m[2], value, flags=re.I)
                outgoing.append((key, value))
            head_length = response.getheader('Content-Length', '0')
            self.reply(response.status, data, outgoing, int(head_length) if self.command == 'HEAD' and head_length.isdigit() else None)
        finally:
            connection.close()

    def do_GET(self):
        try:
            self.handle_request()
        except (ValueError, KeyError, TypeError) as error:
            self.json_reply(400, {'error': str(error)})
        except (OSError, RuntimeError, subprocess.SubprocessError, http.client.HTTPException):
            self.json_reply(502, {'error': 'Backend или VM не отвечает. Проверьте status и логи.'})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = do_GET


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve'])
    parser.add_argument('--base', type=Path, required=True)
    args = parser.parse_args()
    Gateway(args.base).serve_forever()
