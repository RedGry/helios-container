"""Exercise native lifecycle against a disposable QMP fixture, never the live VM."""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import tempfile

def fake(base):
    base = Path(base)
    vm = base / 'vm'
    sock = socket.socket(socket.AF_UNIX)
    (vm/'qmp.sock').unlink(missing_ok=True)
    sock.bind(str(vm/'qmp.sock'))
    sock.listen(4)
    (vm/'qemu.pid').write_text(str(os.getpid()))
    (vm/'ready.pid').write_text(str(os.getpid()))
    while True:
        conn, _ = sock.accept()
        with conn, conn.makefile('rwb') as stream:
            stream.write(b'{"QMP":{}}\n'); stream.flush()
            for line in stream:
                request = json.loads(line)
                stream.write(b'{"event":"TEST"}\n')
                if request['execute'] == 'human-monitor-command':
                    (vm/'forward.command').write_text(request['arguments']['command-line'])
                    stream.write(b'{"return":""}\n')
                else:
                    stream.write(b'{"return":{}}\n')
                stream.flush()
                if request['execute'] in ('system_powerdown','quit'):
                    return

if len(sys.argv) > 1 and sys.argv[1] == '--fake-qemu':
    fake(sys.argv[2]); sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == '--spawn':
    base = Path(sys.argv[2])
    (base/'vm/qemu.argv').write_text(json.dumps(sys.argv[3:]))
    child = subprocess.Popen([sys.executable,__file__,'--fake-qemu',str(base),'qemu-system-x86_64',str(base/'vm/docker.qcow2')],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    for _ in range(100):
        if (base/'vm/ready.pid').exists() and (base/'vm/ready.pid').read_text()==str(child.pid): sys.exit(0)
        time.sleep(.02)
    sys.exit(1)

root = Path(tempfile.mkdtemp(prefix='hc-native-test-')).resolve()
base = root/'fixture-vm'
binary = Path(sys.argv[1]).resolve()
vm = base/'vm'; vm.mkdir(parents=True)
qemu = base/'qemu/usr/local/bin/qemu-system-x86_64'; qemu.parent.mkdir(parents=True)
qemu.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(__file__)+' --spawn '+shlex.quote(str(base))+' "$@"\n')
qemu.chmod(0o700)
config = {'memory_mib':1024,'cpus':1,'ssh_port':40328,'forwards':[],'auto_stop':False,'future_field':{'keep':True}}
(base/'config.json').write_text(json.dumps(config))
disk = vm/'docker.qcow2'
disk.write_bytes(b'guest-data-preserved')
image = qemu.parent/'qemu-img'
image.write_text('#!/bin/sh\ncase "$1" in\n'
                 'convert) printf partial > "$8"; test ! -f '+shlex.quote(str(vm/'convert-fail'))+' || exit 2; cp "$7" "$8";;\n'
                 'compare) test ! -f '+shlex.quote(str(vm/'compare-fail'))+' || exit 3; cmp "$6" "$7";;\n'
                 '*) exit 4;;\nesac\n')
image.chmod(0o700)
fixture_bin = root/'bin'
fixture_bin.mkdir()
ssh = fixture_bin/'ssh'
ssh.write_text('#!/bin/sh\nprintf trim > '+shlex.quote(str(vm/'trim.called'))+'\n')
ssh.chmod(0o700)
def run(args, success=True, home=None):
    environment = dict(os.environ)
    environment['PATH'] = str(fixture_bin)+os.pathsep+environment['PATH']
    if home: environment['HOME'] = str(home)
    result = subprocess.run([str(binary),'--base',str(base),*args],capture_output=True,text=True,timeout=20,env=environment)
    assert (result.returncode==0)==success, (args,result.returncode,result.stderr)
    return result
try:
    run(['configure','--cpus','8'])
    assert json.loads((base/'config.json').read_text())['future_field']=={'keep':True}
    run(['start'])
    args = json.loads((vm/'qemu.argv').read_text())
    assert args[args.index('-accel')+1]=='tcg' and args[args.index('-smp')+1]=='8'
    run(['configure','--memory','512'],success=False)
    run(['forward','18080'])
    command = (vm/'forward.command').read_text()
    assert command.startswith('hostfwd_add net0 tcp:127.0.0.1:') and command.endswith('-:18080')
    assert json.loads((base/'config.json').read_text())['future_field']=={'keep':True}
    run(['stop'])
    run(['configure','--cpus','9'],success=False)
    assert json.loads((base/'config.json').read_text())['cpus']==8
    profile = root/'.profile'; profile.write_text('export KEEP=value\n')
    run(['profile'],home=root)
    once = profile.read_text()
    run(['profile'],home=root)
    assert profile.read_text()==once and once.startswith('export KEEP=value\n')
    assert (base/'profile.before').read_text()=='export KEEP=value\n'
    run(['compact'],home=root)
    assert disk.read_bytes()==b'guest-data-preserved'
    for failure in ('convert-fail','compare-fail'):
        marker = vm/failure
        marker.touch()
        run(['compact'],success=False,home=root)
        assert disk.read_bytes()==b'guest-data-preserved'
        assert not list(vm.glob('.compact-*.qcow2'))
        marker.unlink()
    managed_bin = root/'.local/bin'
    managed_bin.mkdir(parents=True)
    (managed_bin/'helios-container').write_text(
        '#!/bin/sh\n# helios-container managed launcher\nexec '
        + "'" + str(base/'helios-container-native').replace("'", "'\"'\"'")
        + "' --base '" + str(base).replace("'", "'\"'\"'") + "' \"$@\"\n")
    (managed_bin/'docker').write_text('foreign docker command')
    public = root/'public_html/helios-container'
    public.mkdir(parents=True)
    (public/'index.php').write_text('// helios-container managed web gateway')
    (public/'.htaccess').write_text('# helios-container managed web methods')
    (public/'keep.html').write_text('frontend')
    run(['start'],home=root)
    before_compact_pid = (vm/'qemu.pid').read_text()
    run(['compact'],home=root)
    assert disk.read_bytes()==b'guest-data-preserved'
    assert (vm/'trim.called').exists()
    assert (vm/'qemu.pid').read_text()!=before_compact_pid
    (vm/'compare-fail').touch()
    before_failure_pid = (vm/'qemu.pid').read_text()
    failure = run(['compact'],success=False,home=root)
    assert 'Данные диска сохранены' in failure.stderr
    assert disk.read_bytes()==b'guest-data-preserved'
    assert (vm/'qemu.pid').read_text()!=before_failure_pid
    assert not list(vm.glob('.compact-*.qcow2'))
    (vm/'compare-fail').unlink()
    (base/'web.json').write_text(json.dumps({'directory':str(public)}))
    run(['uninstall'],success=False,home=root)
    assert base.exists() and (base/'web.json').exists()
    run(['uninstall','--yes'],home=root)
    assert not base.exists()
    assert not (managed_bin/'helios-container').exists()
    assert (managed_bin/'docker').read_text()=='foreign docker command'
    assert profile.read_text().strip()=='export KEEP=value'
    assert (public/'keep.html').read_text()=='frontend'
    assert not (public/'index.php').exists() and not (public/'.htaccess').exists()
    print('Native fixture OK: lifecycle, forwarding, settings, profile and one-command uninstall')
finally:
    # This is the fixture directory created above, never the live installation.
    assert base.resolve().is_relative_to(root) and base.name.startswith('fixture-')
    try:
        pid=int((vm/'qemu.pid').read_text())
        command=subprocess.check_output(['ps','-ww','-p',str(pid),'-o','command='],text=True)
        if '--fake-qemu' in command and str(base) in command: os.kill(pid,signal.SIGTERM)
    except (OSError,ValueError,subprocess.CalledProcessError):
        pass
    shutil.rmtree(root)
