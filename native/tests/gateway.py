"""Native agent contract tests. Run on FreeBSD with a built binary, no real VM."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

BINARY = str(Path(sys.argv.pop(1)).resolve())

class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Length', '7')
        self.end_headers()
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/login')
            self.end_headers()
            return
        if self.path == '/cookies':
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=ok; Path=/; HttpOnly')
            self.send_header('Set-Cookie', 'other=yes; Domain=127.0.0.1; Path=/api')
            self.end_headers()
            return
        data = json.dumps({'path': self.path, 'method': self.command,
            'body': self.rfile.read(int(self.headers.get('Content-Length', 0))).decode(),
            'auth': self.headers.get('Authorization'), 'admin': self.headers.get('X-HC-Admin'),
            'bridge': self.headers.get('X-HC-Bridge'),
            'prefix': self.headers.get('X-Forwarded-Prefix')}).encode()
        self.send_response(201)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    do_POST = do_GET

class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='hc-native-test-', dir=Path.home())
        cls.base = Path(cls.temp.name)
        (cls.base/'vm').mkdir()
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.target = cls.backend.server_port
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            cls.port = listener.getsockname()[1]
        (cls.base/'config.json').write_text(json.dumps({'memory_mib':1024,'cpus':1,'ssh_port':28022,'auto_stop':False,'forwards':[]}))
        cls.state = {'agent_port':cls.port,'bridge_key':'b'*64,'admin_key':'a'*64,
            'routes':[{'kind':'host','port':cls.target,'target':cls.target}, {'kind':'vm','port':8080,'target':cls.target}]}
        (cls.base/'web.json').write_text(json.dumps(cls.state))
        cls.agent = subprocess.Popen([BINARY,'--base',str(cls.base),'_agent'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if cls.request('/_health')[0] == 200: return
            except OSError: pass
            if cls.agent.poll() is not None: raise AssertionError('Native agent exited')
            time.sleep(.05)
        raise AssertionError('Native agent did not start')
    @classmethod
    def tearDownClass(cls):
        cls.agent.terminate()
        cls.agent.wait(timeout=10)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.temp.cleanup()
    @classmethod
    def request(cls, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=10)
        connection.request(method,path,body,{'X-HC-Bridge':'b'*64,'X-HC-Prefix':'/~student/helios-container/index.php',**(headers or {})})
        response=connection.getresponse()
        result=response.status,response.getheaders(),response.read()
        connection.close()
        return result
    def test_bridge_and_admin_before_dispatch(self):
        self.assertEqual(self.request('/_health',headers={'X-HC-Bridge':'wrong'})[0],403)
        for path in ['/_dashboard','/_logs?id='+'a'*64,'/_config','/_action']:
            self.assertEqual(self.request(path)[0],401)
            self.assertEqual(self.request(path,headers={'X-HC-Admin':'wrong'})[0],401)
    def test_proxy_preserves_body_query_and_application_auth(self):
        code,_,raw=self.request(f'/host/{self.target}/api?a=1','POST','hello',{'Authorization':'Bearer application','X-HC-Admin':'a'*64})
        data=json.loads(raw)
        self.assertEqual(code,201)
        self.assertEqual((data['path'],data['method'],data['body'],data['auth']),('/api?a=1','POST','hello','Bearer application'))
        self.assertIsNone(data['admin'])
        self.assertIsNone(data['bridge'])
    def test_redirect_and_duplicate_cookies(self):
        prefix=f'/~student/helios-container/index.php/host/{self.target}'
        code,headers,_=self.request(f'/host/{self.target}/redirect')
        self.assertEqual(code,302)
        self.assertEqual({k.lower():v for k,v in headers}['location'],prefix+'/login')
        _,headers,_=self.request(f'/host/{self.target}/cookies')
        cookies=[v for k,v in headers if k.lower()=='set-cookie']
        self.assertEqual(len(cookies),2)
        self.assertIn('Path='+prefix+'/',cookies[0])
        self.assertNotIn('Domain=',cookies[1])
    def test_head_and_encoded_path(self):
        code,headers,body=self.request(f'/host/{self.target}/','HEAD')
        self.assertEqual((code,dict(headers)['Content-Length'],body),(200,'7',b''))
        self.assertEqual(json.loads(self.request(f'/host/{self.target}/with%20space?q=%2F')[2])['path'],'/with%20space?q=%2F')
    def test_route_and_vm_state_checked(self):
        self.assertEqual(self.request('/host/22/')[0],404)
        self.assertEqual(self.request('/vm/8080/')[0],503)
    def test_bounded_private_payloads_and_invalid_actions(self):
        auth={'X-HC-Admin':'a'*64}
        self.assertEqual(self.request('/_action','DELETE',headers=auth)[0],405)
        self.assertEqual(self.request('/_action','POST','x'*4097,auth)[0],413)
        self.assertEqual(self.request('/_action','POST','{"action":"exec"}',auth)[0],400)
        self.assertEqual(self.request('/_logs?id=--help',headers=auth)[0],400)
    def test_initial_snapshot_does_not_wait_for_vm(self):
        start=time.monotonic()
        code,headers,body=self.request('/_dashboard',headers={'X-HC-Admin':'a'*64})
        self.assertEqual(code,200)
        self.assertLess(time.monotonic()-start,1)
        self.assertEqual(dict(headers)['Cache-Control'],'no-store')
        self.assertNotIn(b'a'*64,body)
        self.assertFalse(json.loads(body)['vm']['running'])
    def test_invalid_config_preserves_routes(self):
        auth={'X-HC-Admin':'a'*64}
        original=(self.base/'web.json').read_bytes()
        for ports in ['host:22','https://example.com','1,2,3,4,5,6,7,8,9']:
            self.assertEqual(self.request('/_config','POST',json.dumps({'ports':ports}),auth)[0],400)
        self.assertEqual((self.base/'web.json').read_bytes(),original)

unittest.main()
