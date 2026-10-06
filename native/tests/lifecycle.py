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
    subprocess.Popen([sys.executable,__file__,'--fake-qemu',str(base),'qemu-system-x86_64',str(base/'vm/docker.qcow2')],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    for _ in range(100):
        if (base/'vm/ready.pid').exists(): sys.exit(0)
        time.sleep(.02)
    sys.exit(1)

root = Path(tempfile.mkdtemp(prefix='hc-native-test-')).resolve()
base = root/'fixture-vm'
binary = Path(sys.argv[1]).resolve()
vm = base/'vm'; vm.mkdir(parents=True)
qemu = base/'qemu/usr/local/bin/qemu-system-x86_64'; qemu.parent.mkdir(parents=True)
qemu.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(__file__)+' --spawn '+shlex.quote(str(base))+' "$@"\n')
qemu.chmod(0o700)
config = {'memory_mib':1024,'cpus':1,'ssh_port':40328,'forwards':[],'future_field':{'keep':True}}
(base/'config.json').write_text(json.dumps(config))
def run(args, success=True, home=None):
    environment = dict(os.environ)
    if home: environment['HOME'] = str(home)
    result = subprocess.run([str(binary),'--base',str(base),*args],capture_output=True,text=True,timeout=20,env=environment)
    assert (result.returncode==0)==success, (args,result.returncode,result.stderr)
    return result
try:
    run(['configure','--cpus','2'])
    assert json.loads((base/'config.json').read_text())['future_field']=={'keep':True}
    run(['start'])
    args = json.loads((vm/'qemu.argv').read_text())
    assert args[args.index('-accel')+1]=='tcg' and args[args.index('-smp')+1]=='2'
    run(['configure','--memory','512'],success=False)
    run(['forward','18080'])
    command = (vm/'forward.command').read_text()
    assert command.startswith('hostfwd_add net0 tcp:127.0.0.1:') and command.endswith('-:18080')
    assert json.loads((base/'config.json').read_text())['future_field']=={'keep':True}
    run(['stop'])
    run(['configure','--cpus','5'],success=False)
    assert json.loads((base/'config.json').read_text())['cpus']==2
    profile = root/'.profile'; profile.write_text('export KEEP=value\n')
    run(['profile'],home=root)
    once = profile.read_text()
    run(['profile'],home=root)
    assert profile.read_text()==once and once.startswith('export KEEP=value\n')
    assert (base/'profile.before').read_text()=='export KEEP=value\n'
    shutil.copy2(binary,base/'helios-container-native')
    bindir=root/'.local/bin'; bindir.mkdir(parents=True)
    original={}
    for name in ('helios-container','docker'):
        path=bindir/name
        path.write_text('#!/bin/sh\n# helios-container managed launcher\nexec '+str(base/'runtime.py')+' "$@"\n')
        path.chmod(0o700); original[name]=path.read_bytes()
    run(['adopt'],home=root)
    assert all(b'helios-container-native' in (bindir/name).read_bytes() for name in original)
    run(['rollback'],home=root)
    assert all((bindir/name).read_bytes()==old for name,old in original.items())
    print('Native fixture OK: start, QMP, forwarding, graceful stop, settings, profile and launcher rollback')
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
