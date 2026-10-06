"""Build and verify the native-only payload accepted by helios-container update.

Developer tooling uses Python 3.11. The installed kit contains only the Rust
binary and VERSION, with no Python dependency.
"""
import argparse
import hashlib
from pathlib import Path
import re
import stat
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ASSET = 'helios-container-freebsd-amd64'
FILES = frozenset((ASSET, ASSET + '.sha256', 'VERSION', 'release-notes.md'))
MAX_BINARY = 16 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Ожидается стабильная версия X.Y.Z.')
    if value == '0.0.0':
        raise ValueError('Выберите версию первого релиза вместо 0.0.0.')
    return value


def no_symlinks(path):
    """Reject links in both the file and its existing parent directories."""
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('Ссылка в пути файла релиза: ' + str(component))
    return path


def regular(path, maximum):
    path = no_symlinks(path)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
        raise ValueError('Недопустимый файл релиза: ' + str(path))
    return path


def notes(root, value):
    version(value)
    text = regular(root / 'CHANGELOG.md', 1024 * 1024).read_text(encoding='utf-8')
    match = re.search(r'^## ' + re.escape(value) + r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not match or not re.search('[а-яА-ЯёЁ]', match[1]) or not re.search(r'^- ', match[1], re.M):
        raise ValueError('Для версии нужен раздел CHANGELOG.md с русским описанием изменений.')
    return match[1].strip() + '\n'


def check(root):
    root = Path(root)
    value = version(regular(root / 'VERSION', 256).read_text(encoding='utf-8').strip())
    cargo = tomllib.loads(regular(root / 'native/Cargo.toml', 65536).read_text(encoding='utf-8'))
    if cargo.get('package', {}).get('version') != value:
        raise ValueError('VERSION не совпадает с package.version в native/Cargo.toml.')
    return value, notes(root, value)


def freebsd_elf(binary):
    path = regular(binary, MAX_BINARY)
    with path.open('rb') as stream:
        header = stream.read(64)
    if (len(header) != 64 or header[:4] != b'\x7fELF' or header[4] != 2
            or header[5] != 1 or header[7] != 9 or header[18:20] != b'\x3e\x00'):
        raise ValueError('Бинарник должен быть ELF64 FreeBSD amd64, не Linux.')
    return path


def build(root, destination, binary):
    value, body = check(root)
    source = freebsd_elf(binary)
    payload = source.read_bytes()
    destination = no_symlinks(destination)
    if destination.exists() and any(item.name not in FILES for item in destination.iterdir()):
        raise ValueError('В каталоге сборки есть посторонние файлы. Выберите пустой каталог.')
    destination.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = no_symlinks(destination / name)
        if target.exists():
            regular(target, MAX_BINARY)
    output = destination / ASSET
    # The whitelist is the entire release bundle. Source files, disks and keys
    # cannot enter it, even when they exist beside the input binary.
    output.write_bytes(payload)
    output.chmod(0o755)
    (destination / (ASSET + '.sha256')).write_bytes(
        (hashlib.sha256(payload).hexdigest() + '  ' + ASSET + '\n').encode('ascii'))
    (destination / 'VERSION').write_bytes((value + '\n').encode('ascii'))
    (destination / 'release-notes.md').write_bytes(body.encode('utf-8'))
    verify(root, destination)
    return output


def verify(root, destination):
    value, body = check(root)
    destination = no_symlinks(destination)
    if not destination.is_dir() or {item.name for item in destination.iterdir()} != FILES:
        raise ValueError('Состав релиза не соответствует нативному updater.')
    for name in FILES:
        regular(destination / name, MAX_BINARY if name == ASSET else 1024 * 1024)
    artifact = freebsd_elf(destination / ASSET)
    expected = regular(destination / (ASSET + '.sha256'), 4096).read_bytes()
    actual = (hashlib.sha256(artifact.read_bytes()).hexdigest() + '  ' + ASSET + '\n').encode('ascii')
    if expected != actual:
        raise ValueError('SHA-256 бинарника или имя файла не совпадает.')
    if (destination / 'VERSION').read_bytes() != (value + '\n').encode('ascii'):
        raise ValueError('Версия комплекта отличается от VERSION.')
    if (destination / 'release-notes.md').read_bytes() != body.encode('utf-8'):
        raise ValueError('Описание релиза отличается от changelog.')


def main():
    parser = argparse.ArgumentParser(description='Нативный релиз FreeBSD amd64 без Python в установке')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Проверить VERSION, Cargo и русский changelog')
    modes.add_argument('--verify', action='store_true', help='Проверить точный комплект, ELF и SHA-256')
    parser.add_argument('--binary', type=Path, help='Готовый бинарник, собранный для FreeBSD amd64')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    try:
        if args.check:
            check(ROOT)
        elif args.verify:
            verify(ROOT, args.output)
        elif args.binary is None:
            parser.error('Для сборки нужен --binary PATH. Скомпилируйте native/build.sh на FreeBSD.')
        else:
            print(build(ROOT, args.output, args.binary))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
