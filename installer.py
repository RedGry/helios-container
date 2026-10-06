#!/usr/bin/env python3
"""Install a private FreeBSD QEMU payload and an Alpine Docker guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

from runtime import Kit, DEFAULT_HOME, free_port, profile_edit

IMAGE_URL = 'https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/alpine-3.24.2-x86_64-cloudinit-r0.qcow2'
IMAGE_SHA512 = 'c9504d23613f304e0cfb6f5fec872e29e5a5a62e2bc64796daf19c14fdddaa87dc252912fd8bdd17f7b8ebf0cd03305e4075993d54de175e6028d6b50414c67f'


def run(*args, **kwargs):
    subprocess.run(list(args), check=True, **kwargs)


def download(url, destination):
    temporary = destination.with_suffix(destination.suffix + '.part')
    run('curl', '-fL', '--retry', '3', '--connect-timeout', '15', '--max-time', '300', '-o', str(temporary), url)
    temporary.replace(destination)


def prerequisites(base):
    if os.getuid() == 0:
        raise RuntimeError('Запустите установщик под обычным пользователем, без sudo.')
    if subprocess.check_output(['uname', '-s'], text=True).strip() != 'FreeBSD' or subprocess.check_output(['uname', '-m'], text=True).strip() != 'amd64':
        raise RuntimeError('Этот kit предназначен для FreeBSD amd64.')
    if not subprocess.check_output(['uname', '-r'], text=True).startswith('14.'):
        raise RuntimeError('Эта сборка проверена для FreeBSD 14.x. Другие версии пока не поддерживаются.')
    if not base.resolve().is_relative_to(Path.home().resolve()) or base.resolve() == Path.home().resolve() or base.is_symlink():
        raise RuntimeError('Каталог установки должен находиться внутри HOME и не быть ссылкой.')
    for tool in ('pkg', 'curl', 'tar', 'makefs', 'ssh', 'scp', 'ssh-keygen', 'ldd'):
        if not shutil.which(tool):
            raise RuntimeError('Не найден обязательный инструмент: ' + tool)
    if not Path('/usr/share/keys/pkg/trusted').is_dir():
        raise RuntimeError('Не найдены системные ключи подписей FreeBSD pkg.')


def qemu_payload(base):
    target = base / 'qemu'
    marker = target / '.complete'
    if marker.exists():
        return
    work = base / '.packages'
    work.mkdir(exist_ok=True)
    for name in ('repos', 'db', 'cache', 'downloads', 'unpacked', 'minimal'):
        (work / name).mkdir(exist_ok=True)
    (work / 'repos/FreeBSD.conf').write_text('FreeBSD: { url: "https://pkg.FreeBSD.org/FreeBSD:14:amd64/latest", enabled: yes, signature_type: "fingerprints", fingerprints: "/usr/share/keys/pkg" }\n')
    pkg = ['pkg', '-o', f'REPOS_DIR={work / "repos"}', '-o', f'PKG_DBDIR={work / "db"}',
           '-o', f'PKG_CACHEDIR={work / "cache"}', '-o', 'INSTALL_AS_USER=true']
    print('Скачиваю подписанные пакеты QEMU и зависимости…', flush=True)
    run(*pkg, 'update')
    run(*pkg, 'fetch', '-y', '-d', '-o', str(work / 'downloads'), 'qemu-nox11')
    archives = sorted((work / 'downloads').rglob('*.pkg'))
    if not archives:
        raise RuntimeError('pkg не сохранил архивы.')
    unpacked = work / 'unpacked'
    for archive in archives:
        run('tar', '--no-same-owner', '-xf', str(archive), '-C', str(unpacked), '--exclude', '+*')
    minimal = work / 'minimal'
    def copy(path):
        relative = path.relative_to(unpacked)
        destination = minimal / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            link = os.readlink(path)
            source = unpacked / link.lstrip('/') if link.startswith('/') else path.parent / link
            shutil.copy2(source, destination)
        else:
            shutil.copy2(path, destination)
    for name in ('qemu-system-x86_64', 'qemu-img'):
        copy(unpacked / 'usr/local/bin' / name)
    for path in (unpacked / 'usr/local/lib').glob('*.so*'):
        copy(path)
    modules = unpacked / 'usr/local/lib/qemu'
    if modules.exists():
        shutil.copytree(modules, minimal / 'usr/local/lib/qemu', dirs_exist_ok=True)
    firmware = unpacked / 'usr/local/share/qemu'
    for pattern in ('bios*.bin', 'vgabios*.bin', 'kvmvapic.bin'):
        for path in firmware.glob(pattern):
            copy(path)
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(minimal / 'usr/local/lib')
    env['QEMU_MODULE_DIR'] = str(minimal / 'usr/local/lib/qemu')
    keep = set()
    binaries = [minimal / 'usr/local/bin/qemu-system-x86_64', minimal / 'usr/local/bin/qemu-img']
    if (minimal / 'usr/local/lib/qemu').exists():
        binaries += list((minimal / 'usr/local/lib/qemu').glob('*.so'))
    for binary in binaries:
        output = subprocess.check_output(['ldd', str(binary)], env=env, text=True, stderr=subprocess.STDOUT)
        if 'not found' in output:
            raise RuntimeError('Не хватает библиотек: ' + output)
        for name in re.findall(r'=>\s+(\S+)', output):
            path = Path(name)
            if path.parent == minimal / 'usr/local/lib':
                keep.add(path.name)
    for path in (minimal / 'usr/local/lib').glob('*.so*'):
        if path.name not in keep:
            path.unlink()
    run(str(minimal / 'usr/local/bin/qemu-system-x86_64'), '--version', env=env)
    run(str(minimal / 'usr/local/bin/qemu-img'), '--version', env=env)
    if target.exists():
        shutil.rmtree(target)
    minimal.replace(target)
    marker.write_text('FreeBSD:14:amd64 qemu-nox11\n')
    shutil.rmtree(work)


def guest(base, disk_gib):
    vm = base / 'vm'
    vm.mkdir(mode=0o700, exist_ok=True)
    disk = vm / 'docker.qcow2'
    if not disk.exists():
        image = vm / 'alpine-download.qcow2'
        print('Скачиваю Alpine 3.24.2 и проверяю SHA-512…', flush=True)
        download(IMAGE_URL, image)
        with image.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha512').hexdigest()
        if actual != IMAGE_SHA512:
            raise RuntimeError('SHA-512 образа не совпадает. Файл не используется.')
        env = os.environ.copy(); env['LD_LIBRARY_PATH'] = str(base / 'qemu/usr/local/lib')
        run(str(base / 'qemu/usr/local/bin/qemu-img'), 'resize', str(image), f'{disk_gib}G', env=env)
        image.replace(disk)
    key = vm / 'guest-key'
    if not key.exists():
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key))
    key.chmod(0o600)
    seed = vm / 'seed'
    seed.mkdir(mode=0o700, exist_ok=True)
    metadata = seed / 'meta-data'
    if not metadata.exists():
        metadata.write_text(f'instance-id: hc-{uuid.uuid4()}\nlocal-hostname: helios-container\n')
    (seed / 'user-data').write_text('''#cloud-config
hostname: helios-container
disable_root: false
ssh_pwauth: false
users:
  - name: root
    lock_passwd: false
    hashed_passwd: '*'
    ssh_authorized_keys:
      - ''' + key.with_suffix('.pub').read_text().strip() + '''
write_files:
  - path: /etc/apk/repositories
    content: |
      https://dl-cdn.alpinelinux.org/alpine/v3.24/main
      https://dl-cdn.alpinelinux.org/alpine/v3.24/community
  - path: /etc/docker/daemon.json
    content: |
      {"log-driver":"local","log-opts":{"max-size":"10m","max-file":"3"}}
  - path: /root/install-docker.sh
    permissions: '0700'
    content: |
      #!/bin/sh
      set -eu
      apk update
      apk add docker docker-cli-compose openssh-client util-linux-misc
      mkdir -p /workspace
      rc-update add cgroups boot
      rc-service cgroups start
      rc-update add docker default
      rc-service docker start
      for i in $(seq 1 90); do
        if docker info >/dev/null 2>&1; then
          touch /root/docker-ready
          exit 0
        fi
        sleep 2
      done
      exit 1
runcmd:
  - [sh, -c, '/root/install-docker.sh > /root/install-docker.log 2>&1']
''')
    iso = vm / 'seed.iso'
    if not iso.exists():
        run('makefs', '-t', 'cd9660', '-o', 'rockridge,label=cidata', str(iso), str(seed))


def launchers(base):
    bindir = Path.home() / '.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    marker = '# helios-container managed launcher'
    for name, args in [('helios-container', ''), ('docker', ' docker')]:
        path = bindir / name
        if path.is_symlink() or (path.exists() and marker not in path.read_text()):
            raise RuntimeError(f'{path} уже существует и не принадлежит kit. Файл сохранён.')
        path.write_text('#!/bin/sh\n' + marker + '\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(base / 'runtime.py')) + args + ' "$@"\n')
        path.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description='Установка helios-container без root')
    parser.add_argument('--prefix', type=Path, default=DEFAULT_HOME)
    parser.add_argument('--memory', type=int, default=1024, help='RAM гостя в МиБ')
    parser.add_argument('--cpus', type=int, default=1)
    parser.add_argument('--disk', type=int, default=12, help='Виртуальный размер диска в ГиБ')
    parser.add_argument('--no-profile', action='store_true')
    parser.add_argument('--no-launchers', action='store_true')
    args = parser.parse_args()
    base = args.prefix.expanduser().resolve()
    prerequisites(args.prefix.expanduser())
    if not (512 <= args.memory <= 16384 and 1 <= args.cpus <= 4 and 4 <= args.disk <= 64):
        raise RuntimeError('RAM: 512–16384 МиБ, CPU: 1–4, диск: 4–64 ГиБ.')
    os.umask(0o077)
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    base.chmod(0o700)
    config = base / 'config.json'
    if not config.exists():
        config.write_text(json.dumps({'memory_mib': args.memory, 'cpus': args.cpus, 'ssh_port': free_port(), 'forwards': []}, indent=2) + '\n')
    kit = Kit(base)
    if kit.pid():
        print('VM уже работает: обновляю только команды и документацию.', flush=True)
    else:
        if not (base / 'qemu/.complete').exists() and shutil.disk_usage(base).free < 2 * 1024**3:
            raise RuntimeError('Для установки требуется минимум 2 ГиБ свободного места.')
        qemu_payload(base)
        guest(base, args.disk)
    source = Path(__file__).resolve().parent
    for name in ('runtime.py', 'profile.py', 'gateway.py', 'gateway.php', 'gateway.htaccess', 'README.md'):
        if (source / name).resolve() != (base / name).resolve():
            shutil.copy2(source / name, base / name)
    if not args.no_launchers:
        launchers(base)
    if not args.no_profile:
        profile_edit(base=base)
    kit.start(wait=True)
    print('\nГотово. В текущей оболочке выполните: . ~/.profile\nЗатем: docker run --rm hello-world', flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print('Установка не завершена: ' + str(error), file=sys.stderr)
        sys.exit(1)
