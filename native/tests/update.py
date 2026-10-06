import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve()
version = (Path(__file__).resolve().parents[2] / 'VERSION').read_text().strip()
asset = 'helios-container-freebsd-amd64'
url = 'https://github.com/RedGry/helios-container/releases/download/v' + version + '/'
release = {
    'tag_name': 'v' + version,
    'draft': False,
    'prerelease': False,
    'assets': [{'name': name, 'browser_download_url': url + name}
               for name in [asset, asset + '.sha256', 'VERSION']],
}
with tempfile.TemporaryDirectory(prefix='hc-update-test-') as directory:
    root = Path(directory).resolve()
    base = root / 'fixture-kit'
    payload = root / 'payload'
    tools = root / 'tools'
    for path in [base / 'vm', payload, tools]:
        path.mkdir(parents=True)
    preserved = {
        'config.json': json.dumps({'memory_mib': 1024, 'cpus': 8, 'ssh_port': 40328,
                                   'forwards': [], 'auto_stop': False,
                                   'future': {'keep': True}}).encode(),
        'vm/docker.qcow2': b'fixture-disk-do-not-change',
        'vm/guest-key': b'fixture-key-do-not-change',
        'vm/guest-key.pub': b'fixture-public-key-do-not-change',
    }
    for name, content in preserved.items():
        (base / name).write_bytes(content)
    shutil.copy2(binary, payload / asset)
    (payload / 'VERSION').write_text(version + '\n')
    checksum = hashlib.sha256(binary.read_bytes()).hexdigest() + '  ' + asset + '\n'
    (payload / (asset + '.sha256')).write_text(checksum)
    (payload / 'release.json').write_text(json.dumps(release))
    curl = tools / 'curl'
    curl.write_text('#!' + sys.executable + '\n' + '''import os
from pathlib import Path
import shutil
import sys
args = sys.argv[1:]
payload = Path(os.environ['HC_TEST_PAYLOAD'])
if '--output' in args:
    destination = args[args.index('--output') + 1]
    name = args[-1].rsplit('/', 1)[-1]
    shutil.copyfile(payload / name, destination)
else:
    sys.stdout.write((payload / 'release.json').read_text() + '\\n200')
''')
    curl.chmod(0o700)
    environment = dict(os.environ, HOME=str(root), HC_TEST_PAYLOAD=str(payload),
                       PATH=str(tools) + os.pathsep + os.environ['PATH'])
    target = base / 'helios-container-native'
    marker = base / 'VERSION'

    def reset():
        shutil.copy2(binary, target)
        marker.write_text('0.0.0\n')

    def run(command):
        return subprocess.run([str(target), '--base', str(base), *command],
                              env=environment, capture_output=True, text=True, timeout=30)

    def unchanged():
        for name, content in preserved.items():
            assert (base / name).read_bytes() == content, name

    reset()
    result = run(['check-update'])
    assert result.returncode == 0 and 'v' + version in result.stdout, result
    assert marker.read_text() == '0.0.0\n'
    unchanged()
    result = run(['update', '--yes'])
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert target.read_bytes() == binary.read_bytes()
    assert marker.read_text() == version + '\n'
    unchanged()
    reset()
    (payload / (asset + '.sha256')).write_text('0' * 64 + '  ' + asset + '\n')
    result = run(['update', '--yes'])
    assert result.returncode != 0 and 'SHA-256' in result.stderr, result
    assert marker.read_text() == '0.0.0\n'
    assert target.read_bytes() == binary.read_bytes()
    assert not list(base.glob('.native-update-*'))
    unchanged()
    print('Native update fixture OK: notification, update, preserved data, rejected checksum')
