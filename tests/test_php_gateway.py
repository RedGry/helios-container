import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/host/8080/redirect':
            self.send_response(302)
            self.send_header('Location', '/destination')
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        payload = json.dumps({
            'path': self.path,
            'method': self.command,
            'body': body.decode(),
            'headers': dict(self.headers),
        }).encode()
        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Set-Cookie', 'first=1')
        self.send_header('Set-Cookie', 'second=2')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    do_POST = do_GET
    do_HEAD = do_GET


@unittest.skipUnless(shutil.which('php'), 'PHP CLI required')
class PhpGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='helios-php-')
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        source = (ROOT / 'gateway.php').read_text(encoding='utf-8')
        source = source.replace('__HC_PORT__', str(cls.backend.server_port))
        source = source.replace('__HC_BRIDGE__', 'test-bridge')
        router = Path(cls.temp.name) / 'index.php'
        router.write_text(source, encoding='utf-8')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            cls.port = listener.getsockname()[1]
        cls.php = subprocess.Popen(
            ['php', '-d', 'allow_url_fopen=1', '-S', f'127.0.0.1:{cls.port}', str(router)],
            cwd=cls.temp.name, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                cls.request('/index.php')
                return
            except OSError:
                if cls.php.poll() is not None:
                    break
                time.sleep(0.05)
        cls.tearDownClass()
        raise AssertionError('PHP gateway did not start')

    @classmethod
    def tearDownClass(cls):
        cls.php.terminate()
        cls.php.wait(timeout=10)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=10)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def test_dashboard_security_headers(self):
        status, headers, body = self.request('/index.php')
        headers = dict(headers)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertIn(b'<!doctype html>', body)

    def test_dashboard_rejects_post(self):
        self.assertEqual(self.request('/index.php', 'POST')[0], 405)

    def test_unknown_routes_rejected(self):
        for path in ('/unknown', '/host/123456/', '/_dashboard/extra'):
            with self.subTest(path=path):
                self.assertEqual(self.request('/index.php' + path)[0], 404)

    def test_multipart_rejected(self):
        self.assertEqual(self.request('/index.php/_action', 'POST', 'data',
                                     {'Content-Type': 'multipart/form-data; boundary=test'})[0], 415)

    def test_large_request_rejected(self):
        self.assertEqual(self.request('/index.php/_action', 'POST', 'x' * (8 * 1024 * 1024 + 1))[0], 413)

    def test_forwards_query_body_and_safe_headers(self):
        status, _, body = self.request('/index.php/_action?name=a%20b', 'POST', '{"ok":true}', {
            'Content-Type': 'application/json', 'Authorization': 'Bearer test',
            'X-HC-Admin': 'admin', 'X-HC-Bridge': 'forged',
            'X-HC-Prefix': 'forged', 'X-Forwarded-For': 'forged',
            'Connection': 'X-Remove', 'X-Remove': 'secret',
        })
        self.assertEqual(status, 201)
        data = json.loads(body)
        self.assertEqual(data['path'], '/_action?name=a%20b')
        self.assertEqual(data['method'], 'POST')
        self.assertEqual(data['body'], '{"ok":true}')
        headers = {key.lower(): value for key, value in data['headers'].items()}
        self.assertEqual(headers['authorization'], 'Bearer test')
        self.assertEqual(headers['x-hc-admin'], 'admin')
        self.assertEqual(headers['x-hc-bridge'], 'test-bridge')
        self.assertEqual(headers['x-hc-prefix'], '/index.php')
        self.assertNotIn('x-forwarded-for', headers)
        self.assertNotIn('x-remove', headers)

    def test_keeps_duplicate_cookies(self):
        _, headers, _ = self.request('/index.php/host/8080/cookies')
        self.assertEqual([value for name, value in headers if name.lower() == 'set-cookie'],
                         ['first=1', 'second=2'])

    def test_head_has_no_body(self):
        status, headers, body = self.request('/index.php/host/8080/', 'HEAD')
        self.assertEqual(status, 201)
        self.assertGreater(int(dict(headers)['Content-Length']), 0)
        self.assertEqual(body, b'')

    def test_redirect_not_followed(self):
        status, headers, _ = self.request('/index.php/host/8080/redirect')
        self.assertEqual(status, 302)
        self.assertEqual(dict(headers)['Location'], '/destination')

    def test_private_responses_not_cached(self):
        for path in ('/_config', '/_dashboard', '/_logs', '/_action'):
            with self.subTest(path=path):
                status, headers, _ = self.request('/index.php' + path)
                self.assertEqual(status, 201)
                self.assertEqual(dict(headers)['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
