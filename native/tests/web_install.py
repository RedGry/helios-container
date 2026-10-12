import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()
MARKER = '// helios-container managed web gateway'
ACCESS_MARKER = '# helios-container managed web methods'


class WebInstallation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hc-web-install-')
        self.fixture = Path(self.temp.name).resolve()
        self.home = self.fixture / "student's home"
        self.home.mkdir(mode=0o711)
        self.home.chmod(0o711)
        self.base = self.home / 'kit'
        self.bases = [self.base]
        self.base.mkdir()
        (self.base / 'vm').mkdir()
        shutil.copy2(BINARY, self.base / 'helios-container-native')
        (self.base / 'config.json').write_text(json.dumps({
            'memory_mib': 1024, 'cpus': 1, 'ssh_port': 28022,
            'auto_stop': False, 'forwards': [],
        }))
        self.public = self.home / 'public_html'
        self.root = self.public / 'helios-container'
        self.bin = self.fixture / 'bin'
        self.bin.mkdir()
        self.calls = self.fixture / 'curl-calls.jsonl'
        script = self.bin / 'curl.py'
        script.write_text(
            'import json, os, re, sys\n'
            'with open(os.environ["HC_CURL_CALLS"], "a") as stream:\n'
            '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'mode = os.environ.get("HC_CURL_MODE", "ok")\n'
            'if mode == "http-error":\n'
            '    print("curl: (22) The requested URL returned error: 403", file=sys.stderr)\n'
            '    sys.exit(22)\n'
            'if mode == "not-php":\n'
            '    print("<?php echo something;", end="")\n'
            'else:\n'
            '    print(re.search(r"probe-([a-f0-9]+)\\.php$", sys.argv[-1]).group(1), end="")\n'
        )
        curl = self.bin / 'curl'
        curl.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable)
                        + ' ' + shlex.quote(str(script)) + ' "$@"\n')
        curl.chmod(0o755)
        self.env = {
            **os.environ, 'HOME': str(self.home),
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'HC_CURL_CALLS': str(self.calls),
        }

    def tearDown(self):
        self.home.chmod(0o711)
        for base in self.bases:
            if base.exists():
                subprocess.run([str(BINARY), '--base', str(base), 'web', 'stop'],
                               env=self.env, capture_output=True, timeout=15)
        self.temp.cleanup()

    def make_base(self, name):
        base = self.home / name
        base.mkdir()
        (base / 'vm').mkdir()
        shutil.copy2(BINARY, base / 'helios-container-native')
        shutil.copy2(self.base / 'config.json', base / 'config.json')
        self.bases.append(base)
        return base

    def run_web(self, command, success=True, private_umask=False, base=None):
        result = subprocess.run(
            [str(BINARY), '--base', str(base or self.base), 'web', command],
            capture_output=True, text=True, env=self.env, timeout=20,
            preexec_fn=(lambda: os.umask(0o077)) if private_umask else None,
        )
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def run_uninstall(self, base=None):
        result = subprocess.run(
            [str(BINARY), '--base', str(base or self.base), 'uninstall', '--yes'],
            capture_output=True, text=True, env=self.env, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def make_root(self, public_mode=0o755, root_mode=0o755):
        self.public.mkdir(mode=public_mode)
        self.public.chmod(public_mode)
        self.root.mkdir(mode=root_mode)
        self.root.chmod(root_mode)

    def write_state(self, directory=None):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        state = {
            'agent_port': port, 'bridge_key': 'b' * 64, 'admin_key': 'a' * 64,
            'routes': [], 'directory': str(directory or self.root),
            'url': 'https://se.ifmo.ru/~student/helios-container/',
        }
        (self.base / 'web.json').write_text(json.dumps(state))
        return state

    def write_managed_files(self):
        (self.root / 'index.php').write_text('<?php\n' + MARKER + '\n')
        (self.root / '.htaccess').write_text(ACCESS_MARKER + '\n')

    def assert_permission_error(self, path, mode, suggested):
        result = self.run_web('install', success=False)
        self.assertIn(str(path), result.stderr)
        self.assertIn(f'{mode:04o}', result.stderr)
        self.assertIn('chmod ' + suggested + ' ' + shlex.quote(str(path)), result.stderr)
        self.assertEqual(path.stat().st_mode & 0o7777, mode)
        self.assertFalse(self.calls.exists())

    def test_private_home_reports_quoted_chmod_without_widening_permissions(self):
        self.home.chmod(0o700)
        self.assert_permission_error(self.home, 0o700, '711')
        self.assertFalse(self.public.exists())

    def test_existing_public_directory_needs_read_and_search_permissions(self):
        for mode in (0o700, 0o711, 0o744):
            with self.subTest(mode=mode):
                self.public.mkdir(exist_ok=True)
                self.public.chmod(mode)
                self.assert_permission_error(self.public, mode, '755')
                self.assertFalse(self.root.exists())

    def test_repeated_install_checks_existing_gateway_permissions(self):
        self.make_root(root_mode=0o700)
        original = self.write_state()
        self.write_managed_files()
        self.assert_permission_error(self.root, 0o700, '755')
        self.assertEqual(json.loads((self.base / 'web.json').read_text()), original)

    def test_install_preserves_accessible_existing_directory_modes(self):
        self.make_root(public_mode=0o775, root_mode=0o775)
        self.run_web('install')
        self.assertEqual(self.public.stat().st_mode & 0o777, 0o775)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o775)
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o711)
        self.assertEqual(list(self.root.glob('probe-*.php')), [])

    def test_new_directories_are_public_with_private_umask(self):
        self.run_web('install', private_umask=True)
        for directory in (self.public, self.root):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
        for name in ('index.php', '.htaccess'):
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o644)

    def test_repeated_install_preserves_keys_and_skips_php_probe(self):
        self.run_web('install')
        original = (self.base / 'web.json').read_bytes()
        self.env['HC_CURL_MODE'] = 'http-error'
        self.run_web('install')
        self.assertEqual((self.base / 'web.json').read_bytes(), original)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)

    def test_generated_gateway_uses_closed_hex_ownership_and_upgrades_legacy_files(self):
        self.make_root()
        self.write_state()
        self.write_managed_files()
        self.run_web('install')
        owner = '[helios-container base:' + os.fsencode(self.base.resolve()).hex() + ']'
        for name, marker in (('index.php', MARKER), ('.htaccess', ACCESS_MARKER)):
            first_line = (self.root / name).read_text().splitlines()[0]
            self.assertIn(marker + ' ' + owner, first_line)
            self.assertTrue(first_line.isascii())
            self.assertNotIn(str(self.base), first_line)

    def test_http_error_reports_url_and_curl_stderr_and_removes_probe(self):
        self.env['HC_CURL_MODE'] = 'http-error'
        result = self.run_web('install', success=False)
        arguments = json.loads(self.calls.read_text())
        self.assertIn(arguments[-1], result.stderr)
        self.assertIn('curl', result.stderr)
        self.assertIn('403', result.stderr)
        self.assertFalse((self.base / 'web.json').exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_non_php_response_reports_url_and_removes_probe(self):
        self.env['HC_CURL_MODE'] = 'not-php'
        result = self.run_web('install', success=False)
        arguments = json.loads(self.calls.read_text())
        self.assertIn(arguments[-1], result.stderr)
        self.assertIn('не выполняет PHP', result.stderr)
        self.assertFalse((self.base / 'web.json').exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fresh_install_preserves_occupied_foreign_directory(self):
        self.make_root()
        foreign = self.root / 'index.php'
        foreign.write_text('my website')
        self.run_web('install', success=False)
        self.assertEqual(foreign.read_text(), 'my website')
        self.assertFalse(self.calls.exists())

    def test_remove_preserves_foreign_files_and_vm_and_is_idempotent(self):
        self.run_web('install')
        foreign = self.root / 'frontend'
        foreign.mkdir()
        (foreign / 'index.html').write_text('frontend')
        (self.public / 'index.html').write_text('home page')
        (self.base / 'vm' / 'docker.qcow2').write_text('VM data')
        self.run_web('remove')
        self.run_web('remove')
        self.assertEqual((foreign / 'index.html').read_text(), 'frontend')
        self.assertEqual((self.public / 'index.html').read_text(), 'home page')
        self.assertEqual((self.base / 'vm' / 'docker.qcow2').read_text(), 'VM data')
        for name in ('index.php', '.htaccess'):
            self.assertFalse((self.root / name).exists())
        for name in ('web.json', 'web.pid', 'web.log'):
            self.assertFalse((self.base / name).exists())

    def test_remove_without_state_only_removes_managed_files(self):
        self.make_root()
        self.write_managed_files()
        (self.root / 'keep.txt').write_text('keep')
        self.run_web('remove')
        self.assertEqual(list(self.root.iterdir()), [self.root / 'keep.txt'])
        self.run_web('remove')

    def test_uninstall_removes_orphan_gateway_and_preserves_frontend(self):
        self.run_web('install')
        self.run_web('stop')
        for name in ('web.json', 'web.pid', 'web.log'):
            (self.base / name).unlink(missing_ok=True)
        (self.root / 'keep.txt').write_text('frontend')
        self.run_uninstall()
        self.assertFalse(self.base.exists())
        self.assertEqual(list(self.root.iterdir()), [self.root / 'keep.txt'])

    def test_uninstall_other_prefix_preserves_gateway_and_its_installation(self):
        other = self.make_base('kit-other')
        self.run_web('install', base=other)
        original_gateway = {
            name: (self.root / name).read_bytes() for name in ('index.php', '.htaccess')
        }
        original_config = (other / 'config.json').read_bytes()
        original_state = (other / 'web.json').read_bytes()
        launchers = self.home / '.local' / 'bin'
        launchers.mkdir(parents=True)
        original_launchers = {}
        for name in ('helios-container', 'docker'):
            args = ' docker' if name == 'docker' else ''
            text = '#!/bin/sh\n# helios-container managed launcher\nexec '
            text += shlex.quote(str(other / 'helios-container-native'))
            text += ' --base ' + shlex.quote(str(other)) + args + ' "$@"\n'
            (launchers / name).write_text(text)
            (launchers / name).chmod(0o700)
            original_launchers[name] = (launchers / name).read_bytes()
        profile = self.home / '.profile'
        profile.write_text(
            'export KEEP=value\n# >>> helios-container >>>\n'
            'export PATH="$HOME/.local/bin:$PATH"\n# <<< helios-container <<<\n'
        )
        original_profile = profile.read_bytes()
        (self.base / 'web.log').write_text('unrelated old log')
        shutil.copy2(other / 'web.pid', self.base / 'web.pid')
        self.run_uninstall()
        self.assertFalse(self.base.exists())
        self.assertTrue((other / 'helios-container-native').is_file())
        self.assertEqual((other / 'config.json').read_bytes(), original_config)
        self.assertEqual((other / 'web.json').read_bytes(), original_state)
        for name, original in original_gateway.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        for name, original in original_launchers.items():
            self.assertEqual((launchers / name).read_bytes(), original)
        self.assertEqual(profile.read_bytes(), original_profile)
        self.assertIn('работает', self.run_web('info', base=other).stdout)

    def test_uninstall_preserves_legacy_orphan_without_known_owner(self):
        self.make_root()
        self.write_managed_files()
        original_gateway = {
            name: (self.root / name).read_bytes() for name in ('index.php', '.htaccess')
        }
        self.run_uninstall()
        self.assertFalse(self.base.exists())
        for name, original in original_gateway.items():
            self.assertEqual((self.root / name).read_bytes(), original)

    def test_uninstall_stops_local_agent_without_state_and_preserves_unknown_gateway(self):
        self.run_web('install')
        pid = (self.base / 'web.pid').read_text().strip()
        self.write_managed_files()
        (self.base / 'web.json').unlink()
        self.run_uninstall()
        self.assertFalse(self.base.exists())
        self.assertIn(MARKER, (self.root / 'index.php').read_text())
        self.assertIn(ACCESS_MARKER, (self.root / '.htaccess').read_text())
        process = subprocess.run(
            ['ps', '-ww', '-p', pid, '-o', 'command='],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotIn('_agent', process.stdout)

    def test_explicit_remove_and_install_refuse_another_prefix_ownership(self):
        other = self.make_base('kit-other')
        self.run_web('install', base=other)
        original_gateway = {
            name: (self.root / name).read_bytes() for name in ('index.php', '.htaccess')
        }
        self.run_web('remove', success=False)
        shutil.copy2(other / 'web.json', self.base / 'web.json')
        original_state = (self.base / 'web.json').read_bytes()
        for command in ('install', 'remove'):
            result = self.run_web(command, success=False)
            self.assertIn('другой установке', result.stderr)
            self.assertEqual((self.base / 'web.json').read_bytes(), original_state)
            for name, original in original_gateway.items():
                self.assertEqual((self.root / name).read_bytes(), original)
        self.assertIn('работает', self.run_web('info', base=other).stdout)

    def test_state_owned_legacy_gateway_remains_removable(self):
        self.make_root()
        self.write_state()
        self.write_managed_files()
        self.run_web('remove')
        self.assertFalse(self.root.exists())
        self.assertFalse((self.base / 'web.json').exists())

    def test_uninstall_preserves_unrelated_public_symlink_without_state(self):
        outside = self.fixture / 'website'
        outside.mkdir()
        (outside / 'index.php').write_text('website')
        self.public.symlink_to(outside, target_is_directory=True)
        result = subprocess.run(
            [str(BINARY), '--base', str(self.base), 'uninstall', '--yes'],
            capture_output=True, text=True, env=self.env, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.base.exists())
        self.assertTrue(self.public.is_symlink())
        self.assertEqual((outside / 'index.php').read_text(), 'website')

    def test_remove_without_state_preserves_empty_unmanaged_directory(self):
        self.make_root()
        self.run_web('remove')
        self.assertTrue(self.root.is_dir())

    def test_remove_with_missing_root_cleans_state_and_residue(self):
        self.write_state()
        (self.base / 'web.pid').write_text('not a pid')
        (self.base / 'web.log').write_text('old log')
        self.run_web('remove')
        self.run_web('remove')
        for name in ('web.json', 'web.pid', 'web.log'):
            self.assertFalse((self.base / name).exists())

    def test_remove_without_any_web_installation_succeeds(self):
        self.run_web('remove')
        self.assertFalse(self.public.exists())

    def test_remove_refuses_foreign_managed_filename_before_deleting_anything(self):
        self.make_root()
        self.write_state()
        self.write_managed_files()
        (self.root / '.htaccess').write_text('foreign rules')
        self.run_web('remove', success=False)
        self.assertTrue((self.base / 'web.json').exists())
        self.assertIn(MARKER, (self.root / 'index.php').read_text())
        self.assertEqual((self.root / '.htaccess').read_text(), 'foreign rules')

    def test_remove_refuses_state_pointing_outside_expected_directory(self):
        outside = self.fixture / 'outside'
        outside.mkdir()
        (outside / 'index.php').write_text(MARKER)
        self.write_state(directory=outside)
        self.run_web('remove', success=False)
        self.assertEqual((outside / 'index.php').read_text(), MARKER)
        self.assertTrue((self.base / 'web.json').exists())

    def test_public_symlink_is_refused_for_install_and_remove(self):
        outside = self.fixture / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('keep')
        self.public.symlink_to(outside, target_is_directory=True)
        for command in ('install', 'remove'):
            self.run_web(command, success=False)
        self.assertTrue(self.public.is_symlink())
        self.assertEqual(list(outside.iterdir()), [outside / 'keep.txt'])

    def test_gateway_symlink_is_refused_for_remove(self):
        self.public.mkdir()
        outside = self.fixture / 'outside'
        outside.mkdir()
        (outside / 'index.php').write_text(MARKER)
        self.root.symlink_to(outside, target_is_directory=True)
        self.write_state()
        self.run_web('remove', success=False)
        self.assertTrue(self.root.is_symlink())
        self.assertEqual((outside / 'index.php').read_text(), MARKER)
        self.assertTrue((self.base / 'web.json').exists())

    def test_gateway_file_symlink_is_refused_before_other_files_are_removed(self):
        self.make_root()
        self.write_state()
        self.write_managed_files()
        outside = self.fixture / 'outside.php'
        outside.write_text(MARKER)
        (self.root / 'index.php').unlink()
        (self.root / 'index.php').symlink_to(outside)
        self.run_web('remove', success=False)
        self.assertTrue((self.root / 'index.php').is_symlink())
        self.assertTrue((self.root / '.htaccess').exists())
        self.assertTrue((self.base / 'web.json').exists())
        self.assertEqual(outside.read_text(), MARKER)


unittest.main()
