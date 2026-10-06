import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_HEAD(self):
        self.send_response(200); self.send_header('Content-Length', '7'); self.end_headers()
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location', '/login'); self.end_headers(); return
        if self.path == '/cookies':
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=ok; Path=/; HttpOnly')
            self.send_header('Set-Cookie', 'other=yes; Domain=127.0.0.1; Path=/api')
            self.end_headers(); return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
        data = json.dumps({'path': self.path, 'method': self.command, 'body': body, 'auth': self.headers.get('Authorization'), 'admin': self.headers.get('X-HC-Admin'), 'prefix': self.headers.get('X-Forwarded-Prefix')}).encode()
        self.send_response(201); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    do_POST = do_GET


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.target = self.backend.server_port
        (self.base / 'config.json').write_text(json.dumps({'memory_mib': 1024, 'cpus': 1, 'ssh_port': 28022}))
        gateway.save(self.base, {'agent_port': 0, 'bridge_key': 'bridge-secret', 'admin_key': 'admin-secret', 'routes': [{'kind': 'host', 'port': self.target, 'target': self.target}]})
        self.server = gateway.Gateway(self.base)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.owned = patch.object(gateway, 'owned_listener', return_value=True)
        self.owned.start()

    def tearDown(self):
        self.owned.stop()
        self.server.shutdown(); self.server.server_close()
        self.backend.shutdown(); self.backend.server_close()
        self.directory.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body, {'X-HC-Bridge': 'bridge-secret', 'X-HC-Prefix': '/~student/helios-container/index.php', **(headers or {})})
        response = connection.getresponse()
        result = response.status, response.getheaders(), response.read()
        connection.close(); return result

    def test_configuration_requires_admin_and_only_allows_owned_host_ports(self):
        self.assertEqual(self.request('/_config', 'POST', '{"ports":"host:3000"}')[0], 401)
        with patch.object(gateway, 'owned_listener', return_value=False):
            self.assertEqual(self.request('/_config', 'POST', '{"ports":"host:3000"}', {'X-HC-Admin': 'admin-secret'})[0], 400)
        self.assertEqual(self.server.state['routes'][0]['port'], self.target)
        self.assertEqual(self.request('/host/22/')[0], 404)
        self.assertEqual(self.request('/_health', headers={'X-HC-Bridge': 'wrong'})[0], 403)

    def test_proxy_preserves_method_query_body_status_and_auth_without_admin_key(self):
        code, headers, raw = self.request(f'/host/{self.target}/api?a=1', 'POST', 'hello', {'Authorization': 'Bearer application', 'X-HC-Admin': 'admin-secret'})
        data = json.loads(raw)
        self.assertEqual(code, 201)
        self.assertEqual((data['path'], data['method'], data['body'], data['auth']), ('/api?a=1', 'POST', 'hello', 'Bearer application'))
        self.assertIsNone(data['admin'])

    def test_redirect_and_cookie_paths_stay_under_proxy_prefix(self):
        prefix = f'/~student/helios-container/index.php/host/{self.target}'
        code, headers, body = self.request(f'/host/{self.target}/redirect')
        self.assertEqual(code, 302)
        self.assertEqual(dict(headers)['Location'], prefix + '/login')
        code, headers, body = self.request(f'/host/{self.target}/cookies')
        cookies = [v for k, v in headers if k == 'Set-Cookie']
        self.assertEqual(len(cookies), 2)
        self.assertIn('Path=' + prefix + '/', cookies[0])
        self.assertNotIn('Domain=', cookies[1])

    def test_route_is_denied_if_host_port_changes_owner(self):
        with patch.object(gateway, 'owned_listener', return_value=False):
            self.assertEqual(self.request(f'/host/{self.target}/')[0], 503)

    def test_head_and_encoded_path_are_preserved(self):
        code, headers, data = self.request(f'/host/{self.target}/', 'HEAD')
        self.assertEqual((code, dict(headers)['Content-Length'], data), (200, '7', b''))
        code, headers, data = self.request(f'/host/{self.target}/api/with%20space')
        self.assertEqual(json.loads(data)['path'], '/api/with%20space')

    def test_port_input_rejects_urls_privileged_host_ports_and_too_many_routes(self):
        for value in ('https://example.com', 'host:22', '65536', '3000:80', '1,2,3,4,5,6,7,8,9'):
            with self.assertRaises(ValueError): gateway.parse_ports(value)
        self.assertEqual(gateway.parse_ports('8080, 8080 host:3000'), [{'kind': 'vm', 'port': 8080}, {'kind': 'host', 'port': 3000}])


class RemovalTests(unittest.TestCase):
    def test_removal_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); base = home / 'kit'; base.mkdir()
            root = home / 'public_html/helios-container'; root.mkdir(parents=True)
            (root / 'index.php').write_text('<?php ' + gateway.MARKER)
            (root / '.htaccess').write_text('# helios-container managed web methods')
            (root / 'my-page.html').write_text('user content')
            gateway.save(base, {'directory': str(root)})
            with patch.object(gateway.Path, 'home', return_value=home), patch.object(gateway, 'stop_agent'):
                gateway.manage(SimpleNamespace(base=base), ['remove'])
            self.assertEqual((root / 'my-page.html').read_text(), 'user content')
            self.assertFalse((root / 'index.php').exists())
            self.assertFalse((root / '.htaccess').exists())

    def test_removal_refuses_foreign_htaccess(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); base = home / 'kit'; base.mkdir()
            root = home / 'public_html/helios-container'; root.mkdir(parents=True)
            (root / 'index.php').write_text('<?php ' + gateway.MARKER)
            (root / '.htaccess').write_text('user settings')
            gateway.save(base, {'directory': str(root)})
            with patch.object(gateway.Path, 'home', return_value=home), patch.object(gateway, 'stop_agent'):
                with self.assertRaises(RuntimeError): gateway.manage(SimpleNamespace(base=base), ['remove'])
            self.assertEqual((root / '.htaccess').read_text(), 'user settings')
            self.assertTrue((root / 'index.php').exists())
