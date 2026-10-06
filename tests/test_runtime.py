import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hc_runtime', SOURCE / 'runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class ProfileTests(unittest.TestCase):
    def test_preserves_user_profile_and_idempotent_block(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            base = home / 'kit'; base.mkdir()
            original = '# настройки\nexport EDITOR=vim\nexport PATH=/my/tools:$PATH'.encode()
            profile = home / '.profile'; profile.write_bytes(original)
            with patch.object(runtime.Path, 'home', return_value=home):
                runtime.profile_edit(base=base)
                runtime.profile_edit(base=base)
                content = profile.read_bytes()
                self.assertTrue(content.startswith(original))
                self.assertEqual(content.count(runtime.PROFILE_BEGIN), 1)
                self.assertEqual((base / 'profile.before').read_bytes(), original)
                runtime.profile_edit(install=False, base=base)
                self.assertEqual(profile.read_bytes(), original)

    def test_refuses_malformed_marker_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = b'export EDITOR=vim\n' + runtime.PROFILE_BEGIN + b'\n'
            (home / '.profile').write_bytes(original)
            with patch.object(runtime.Path, 'home', return_value=home):
                with self.assertRaises(RuntimeError):
                    runtime.profile_edit(base=home)
            self.assertEqual((home / '.profile').read_bytes(), original)


class OwnershipTests(unittest.TestCase):
    def test_stale_pid_cannot_control_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'vm').mkdir()
            (base / 'vm/qemu.pid').write_text('1234')
            (base / 'config.json').write_text(json.dumps({'memory_mib': 1024, 'cpus': 1, 'ssh_port': 28022}))
            kit = runtime.Kit(base)
            with patch.object(runtime.os, 'getuid', return_value=1000, create=True):
                with patch.object(runtime.subprocess, 'check_output', return_value='1000 unrelated-service\n'):
                    self.assertIsNone(kit.pid())
                with patch.object(runtime.subprocess, 'check_output', return_value=f'1001 qemu-system-x86_64 {base / "vm/docker.qcow2"}\n'):
                    self.assertIsNone(kit.pid())
                with patch.object(runtime.subprocess, 'check_output', return_value=f'1000 qemu-system-x86_64 -drive file={base / "vm/docker.qcow2"}\n'):
                    self.assertEqual(kit.pid(), 1234)


if __name__ == '__main__':
    unittest.main()
