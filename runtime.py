#!/usr/bin/env python3
"""Per-user Docker VM on FreeBSD. Standard library only."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time

DEFAULT_HOME = Path.home() / '.local/helios-container'
PROFILE_BEGIN = b'# >>> helios-container >>>'
PROFILE_END = b'# <<< helios-container <<<'


def profile_edit(install=True, base=DEFAULT_HOME):
    profile = Path.home() / '.profile'
    if profile.is_symlink():
        raise RuntimeError('.profile является ссылкой. Настройте PATH вручную.')
    original = profile.read_bytes() if profile.exists() else b''
    start, end = original.find(PROFILE_BEGIN), original.find(PROFILE_END)
    if (start < 0) != (end < 0) or (start >= 0 and end < start):
        raise RuntimeError('Повреждён блок helios-container в .profile.')
    content = original
    if start >= 0:
        end += len(PROFILE_END)
        if original[end:end + 2] == b'\r\n':
            end += 2
        elif original[end:end + 1] == b'\n':
            end += 1
        content = original[:start] + original[end:]
    if not install and (base / 'profile.before').exists():
        backup_content = (base / 'profile.before').read_bytes()
        if backup_content and not backup_content.endswith(b'\n') and content == backup_content + b'\n':
            content = backup_content
    if install:
        backup = base / 'profile.before'
        if not backup.exists():
            backup.write_bytes(original)
            backup.chmod(0o600)
        if content and not content.endswith(b'\n'):
            content += b'\n'
        content += PROFILE_BEGIN + b'\nexport PATH="$HOME/.local/bin:$PATH"\n' + PROFILE_END + b'\n'
    if content != original:
        profile.write_bytes(content)
        if not original:
            profile.chmod(0o600)


def free_port(preferred=0):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', preferred))
        return sock.getsockname()[1]


class Kit:
    def __init__(self, base=None):
        self.base = Path(base or Path(__file__).resolve().parent)
        self.vm = self.base / 'vm'
        self.config = json.loads((self.base / 'config.json').read_text())
        self.validate()

    def validate(self):
        c = self.config
        if not (512 <= c['memory_mib'] <= 16384 and 1 <= c['cpus'] <= 4 and 1024 <= c['ssh_port'] <= 65535):
            raise RuntimeError('Настройки: RAM 512–16384 МиБ, CPU 1–4, SSH-порт 1024–65535.')

    def save(self):
        temporary = self.base / 'config.json.tmp'
        temporary.write_text(json.dumps(self.config, indent=2) + '\n')
        temporary.replace(self.base / 'config.json')

    def pid(self):
        try:
            pid = int((self.vm / 'qemu.pid').read_text())
            output = subprocess.check_output(['ps', '-ww', '-p', str(pid), '-o', 'uid=', '-o', 'command='], text=True)
            uid, command = output.strip().split(None, 1)
            if int(uid) == os.getuid() and 'qemu-system-x86_64' in command and str(self.vm / 'docker.qcow2') in command:
                return pid
        except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
            pass
        return None

    def ssh_options(self, scp=False):
        return ['-P' if scp else '-p', str(self.config['ssh_port']), '-i', str(self.vm / 'guest-key'),
                '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', f'UserKnownHostsFile={self.vm / "known_hosts"}', '-o', 'ConnectTimeout=10']

    def ssh(self, command, tty=False):
        return ['ssh'] + (['-t'] if tty else []) + self.ssh_options() + ['root@127.0.0.1', command]

    def qmp(self, command, arguments=None):
        if not self.pid():
            raise RuntimeError('VM остановлена.')
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(10)
            sock.connect(str(self.vm / 'qmp.sock'))
            stream = sock.makefile('rwb')
            stream.readline()
            answer = None
            for request in [{'execute': 'qmp_capabilities'}, {'execute': command, 'arguments': arguments or {}}]:
                stream.write((json.dumps(request) + '\n').encode())
                stream.flush()
                while True:
                    line = stream.readline()
                    if not line:
                        raise RuntimeError('QMP закрыл соединение.')
                    reply = json.loads(line)
                    if 'error' in reply:
                        raise RuntimeError(str(reply['error']))
                    if 'return' in reply:
                        answer = reply['return']
                        break
            return answer

    def start(self, wait=True):
        if not self.pid():
            c = self.config
            net = f'user,id=net0,hostfwd=tcp:127.0.0.1:{c["ssh_port"]}-:22'
            for mapping in c.get('forwards', []):
                net += f',hostfwd=tcp:127.0.0.1:{mapping["host"]}-:{mapping["guest"]}'
            env = os.environ.copy()
            env['LD_LIBRARY_PATH'] = str(self.base / 'qemu/usr/local/lib')
            env['QEMU_MODULE_DIR'] = str(self.base / 'qemu/usr/local/lib/qemu')
            subprocess.run([str(self.base / 'qemu/usr/local/bin/qemu-system-x86_64'),
                '-L', str(self.base / 'qemu/usr/local/share/qemu'),
                '-machine', 'q35', '-accel', 'tcg', '-cpu', 'max', '-smp', str(c['cpus']),
                '-m', str(c['memory_mib']), '-drive', f'file={self.vm / "docker.qcow2"},format=qcow2,if=virtio,discard=unmap',
                '-drive', f'file={self.vm / "seed.iso"},format=raw,media=cdrom,readonly=on',
                '-netdev', net, '-device', 'virtio-net-pci,netdev=net0,romfile=',
                '-display', 'none', '-monitor', 'none', '-serial', f'file:{self.vm / "console.log"}',
                '-qmp', f'unix:{self.vm / "qmp.sock"},server=on,wait=off',
                '-pidfile', str(self.vm / 'qemu.pid'), '-daemonize'], env=env, check=True, stdin=subprocess.DEVNULL)
            print(f'VM запущена: {c["cpus"]} CPU, {c["memory_mib"]} МиБ RAM. SSH: 127.0.0.1:{c["ssh_port"]}', file=sys.stderr, flush=True)
        if wait:
            self.wait_ready()
        if (self.base / 'web.json').exists():
            from gateway import ensure_agent
            ensure_agent(self.base)

    def wait_ready(self, timeout=600):
        pid = self.pid()
        ready = self.vm / 'ready.pid'
        if pid and ready.exists() and ready.read_text().strip() == str(pid):
            return
        deadline = time.monotonic() + timeout
        next_message = 0
        last = ''
        while time.monotonic() < deadline:
            if not self.pid():
                raise RuntimeError('VM завершилась. Проверьте helios-container logs.')
            if time.monotonic() >= next_message:
                print('Ожидаю Linux и Docker…', file=sys.stderr, flush=True)
                next_message = time.monotonic() + 30
            try:
                result = subprocess.run(self.ssh('docker info --format "{{.ServerVersion}}"'),
                                        capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
                if result.returncode == 0 and result.stdout.strip():
                    ready.write_text(str(pid))
                    print('Docker готов: ' + result.stdout.strip(), file=sys.stderr, flush=True)
                    return
                last = result.stderr.strip()
            except subprocess.TimeoutExpired:
                last = 'SSH пока не отвечает.'
            time.sleep(5)
        raise RuntimeError('Docker не готов за 10 минут. ' + last + '\nДиагностика: helios-container ssh "tail -n 60 /root/install-docker.log"')

    def ensure(self):
        self.start(wait=True)

    def forward(self, guest, preferred=None):
        if not 1 <= guest <= 65535 or (preferred is not None and not 1024 <= preferred <= 65535):
            raise RuntimeError('Порт VM: 1–65535, порт helios: 1024–65535.')
        for mapping in self.config.get('forwards', []):
            if mapping['guest'] == guest:
                return mapping['host']
        self.ensure()
        host = free_port(preferred or 0)
        answer = self.qmp('human-monitor-command', {'command-line': f'hostfwd_add net0 tcp:127.0.0.1:{host}-:{guest}'})
        if answer.strip():
            raise RuntimeError(answer.strip())
        self.config.setdefault('forwards', []).append({'guest': guest, 'host': host})
        self.save()
        return host

    def stop(self, force=False):
        if not self.pid():
            print('VM остановлена.')
            return
        self.qmp('quit' if force else 'system_powerdown')
        deadline = time.monotonic() + 120
        while self.pid() and time.monotonic() < deadline:
            time.sleep(1)
        if self.pid():
            raise RuntimeError('Выключение ещё не завершилось. Повторите status. stop --force завершает VM без корректного выключения.')
        print('VM остановлена.')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    kit = Kit()
    if argv and argv[0] == 'web':
        from gateway import manage
        return manage(kit, argv[1:])
    if argv and argv[0] == 'docker':
        kit.ensure()
        tty = sys.stdin.isatty() and any(x in ('-it', '-ti', '-t', '--tty', '--tty=true') for x in argv[1:])
        return subprocess.call(kit.ssh(shlex.join(['docker'] + argv[1:]), tty=tty))
    parser = argparse.ArgumentParser(prog='helios-container', description='Docker на helios под вашим пользователем')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('start')
    sub.add_parser('status')
    sub.add_parser('logs')
    sub.add_parser('profile')
    sub.add_parser('web', help='Опциональный HTTPS-шлюз в public_html')
    stop = sub.add_parser('stop'); stop.add_argument('--force', action='store_true')
    shell = sub.add_parser('ssh'); shell.add_argument('command', nargs=argparse.REMAINDER)
    for name in ('upload', 'download'):
        cp = sub.add_parser(name); cp.add_argument('source'); cp.add_argument('destination', nargs='?', default='/workspace' if name == 'upload' else '.')
    forward = sub.add_parser('forward'); forward.add_argument('guest', type=int); forward.add_argument('host', type=int, nargs='?')
    configure = sub.add_parser('configure'); configure.add_argument('--memory', type=int); configure.add_argument('--cpus', type=int); configure.add_argument('--ssh-port', type=int)
    uninstall = sub.add_parser('uninstall'); uninstall.add_argument('--yes', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'start':
        kit.start()
    elif args.action == 'stop':
        kit.stop(args.force)
    elif args.action == 'status':
        c = kit.config
        print(f'{"Работает" if kit.pid() else "Остановлена"}, {c["cpus"]} CPU, {c["memory_mib"]} МиБ RAM, SSH 127.0.0.1:{c["ssh_port"]}')
        if kit.pid():
            subprocess.run(['ps', '-p', str(kit.pid()), '-o', 'pid,rss,%cpu,etime,comm'])
        for mapping in c.get('forwards', []):
            print(f'TCP 127.0.0.1:{mapping["host"]} → VM:{mapping["guest"]}')
    elif args.action == 'logs':
        path = kit.vm / 'console.log'
        if path.exists():
            subprocess.run(['tail', '-n', '60', str(path)])
    elif args.action == 'profile':
        profile_edit(base=kit.base)
        print('PATH настроен. Выполните: . ~/.profile')
    elif args.action == 'configure':
        if kit.pid():
            raise RuntimeError('Сначала выполните helios-container stop.')
        for option, key in [('memory', 'memory_mib'), ('cpus', 'cpus'), ('ssh_port', 'ssh_port')]:
            value = getattr(args, option)
            if value is not None:
                kit.config[key] = value
        kit.validate(); kit.save(); print('Настройки сохранены. Выполните helios-container start.')
    elif args.action == 'ssh':
        kit.ensure()
        command = args.command[0] if len(args.command) == 1 else shlex.join(args.command)
        return subprocess.call(kit.ssh(command, tty=sys.stdin.isatty()))
    elif args.action in ('upload', 'download'):
        kit.ensure()
        source, destination = args.source, args.destination
        remote = destination if args.action == 'upload' else source
        if not remote.startswith('/'):
            raise RuntimeError('Путь внутри VM должен быть абсолютным, например /workspace.')
        if args.action == 'upload':
            destination = 'root@127.0.0.1:' + destination
        else:
            source = 'root@127.0.0.1:' + source
        return subprocess.call(['scp', '-r'] + kit.ssh_options(scp=True) + ['--', source, destination])
    elif args.action == 'forward':
        host = kit.forward(args.guest, args.host)
        print(f'TCP 127.0.0.1:{host} → VM:{args.guest}')
    elif args.action == 'uninstall':
        if not args.yes:
            raise RuntimeError('Удаляет VM, контейнеры и volumes. Для подтверждения: uninstall --yes')
        if kit.pid():
            raise RuntimeError('Сначала выполните helios-container stop.')
        root = kit.base.resolve()
        if not root.is_relative_to(Path.home().resolve()) or root == Path.home().resolve() or kit.base.is_symlink():
            raise RuntimeError('Отказ удаления: установка должна находиться внутри HOME.')
        if (kit.base / 'web.json').exists():
            from gateway import manage
            manage(kit, ['remove'])
        if (kit.base / 'profile.before').exists():
            profile_edit(install=False, base=kit.base)
        for name in ('docker', 'helios-container'):
            launcher = Path.home() / '.local/bin' / name
            if launcher.exists() and not launcher.is_symlink() and '# helios-container managed launcher' in launcher.read_text() and str(kit.base / 'runtime.py') in launcher.read_text():
                launcher.unlink()
        shutil.rmtree(root)
        print('Установка удалена. Остальные файлы HOME сохранены.')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print('helios-container: ' + str(error), file=sys.stderr)
        sys.exit(1)
