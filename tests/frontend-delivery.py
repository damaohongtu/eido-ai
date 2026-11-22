#!/usr/bin/env python3
"""Exercise the real nginx config without a running application or Docker.

Run: python3 tests/frontend-delivery.py (requires nginx on PATH).
"""
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
PC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15'
PHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/api/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: first\n\n')
            self.wfile.flush()
            time.sleep(0.5)
            self.wfile.write(b'data: second\n\n')
            return
        payload = json.dumps({'path': self.path, 'headers': dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@unittest.skipUnless(shutil.which('nginx'), 'nginx is required')
class FrontendDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown()
        cls.backend.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='eido-delivery-')
        self.root = Path(self.temp.name)
        self.port = free_port()
        for directory, marker, assets in [('pc', 'PC', 'assets'), ('mobile', 'H5', 'mobile-assets')]:
            public = self.root / directory / 'ai-eido'
            (public / assets).mkdir(parents=True)
            (public / 'images').mkdir()
            (public / 'index.html').write_text(marker)
            (public / assets / 'app.js').write_text(f'{marker}-JS')
            (public / 'images' / 'logo.png').write_bytes(marker.encode())

    def tearDown(self):
        self.temp.cleanup()

    def start(self, filename):
        config = (REPO / filename).read_text()
        config = config.replace('/var/www/h5', str(self.root / 'mobile'))
        config = config.replace('/var/www', str(self.root / 'pc'))
        config = config.replace('listen 80;', f'listen 127.0.0.1:{self.port};')
        config = config.replace('127.0.0.1:8000', f'127.0.0.1:{self.backend.server_port}')
        config = config.replace('/var/log/eido/nginx/access.log', str(self.root / 'access.log'))
        config = config.replace('/var/log/eido/nginx/error.log', str(self.root / 'error.log'))
        config = config.replace('/var/log/nginx/ai-eido-access.log', str(self.root / 'access.log'))
        config = config.replace('/var/log/nginx/ai-eido-error.log', str(self.root / 'error.log'))
        mime = '/opt/homebrew/etc/nginx/mime.types' if Path('/opt/homebrew/etc/nginx/mime.types').exists() else '/etc/nginx/mime.types'
        full = f'pid {self.root}/nginx.pid;\nerror_log {self.root}/main-error.log;\nevents {{}}\nhttp {{ include {mime};\n{config}\n}}'
        path = self.root / 'nginx.conf'
        path.write_text(full)
        subprocess.run(['nginx', '-t', '-p', str(self.root), '-c', str(path)], check=True, capture_output=True)
        process = subprocess.Popen(['nginx', '-p', str(self.root), '-c', str(path), '-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: self.stop(process))
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode())
            try:
                self.get('/ai-eido/')
                return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError('nginx did not start')

    @staticmethod
    def stop(process):
        process.terminate()
        process.communicate(timeout=5)

    def get(self, path, ua=PC_UA, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request('GET', path, headers={'User-Agent': ua, **(headers or {})})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        return result

    def check_config(self, filename):
        self.start(filename)
        for ua, expected in [(PC_UA, 'PC'), (PHONE_UA, 'H5'), ('Android Tablet', 'H5'), ('iPad', 'H5'), ('HarmonyOS Mobile', 'H5'), ('', 'PC')]:
            for path in ['/ai-eido/', '/ai-eido/index.html', '/ai-eido/some/deep/link?login=success']:
                with self.subTest(ua=ua, path=path):
                    code, headers, body = self.get(path, ua)
                    self.assertEqual((code, body), (200, expected))
                    self.assertIn('User-Agent', headers['Vary'])
                    self.assertIn('no-cache', headers['Cache-Control'])
        for ua in [PC_UA, PHONE_UA]:
            for path, expected in [('/ai-eido/assets/app.js', 'PC-JS'), ('/ai-eido/mobile-assets/app.js', 'H5-JS')]:
                code, headers, body = self.get(path, ua)
                self.assertEqual((code, body), (200, expected))
                self.assertIn('immutable', headers['Cache-Control'])
            for path in ['/ai-eido/assets/missing.js', '/ai-eido/mobile-assets/missing.js', '/ai-eido/images/missing.png']:
                self.assertEqual(self.get(path, ua)[0], 404)
            result = json.loads(self.get('/ai-eido/api/v1/auth/me?probe=1', ua, {'X-Eido-User-Id': 'forged', 'X-Eido-Gateway-Secret': 'forged'})[2])
            self.assertEqual(result['path'], '/api/v1/auth/me?probe=1')
            self.assertNotIn('X-Eido-User-Id', result['headers'])
            self.assertNotIn('X-Eido-Gateway-Secret', result['headers'])
            self.assertEqual(json.loads(self.get('/ai-eido/health', ua)[2])['path'], '/health')
        code, headers, _ = self.get('/ai-eido?login=success')
        self.assertEqual(code, 301)
        self.assertTrue(headers['Location'].endswith('/ai-eido/?login=success'))
        self.assertEqual(self.get('/')[0], 301)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        start = time.monotonic()
        connection.request('GET', '/ai-eido/api/stream', headers={'User-Agent': PHONE_UA})
        response = connection.getresponse()
        self.assertEqual(response.readline(), b'data: first\n')
        self.assertLess(time.monotonic() - start, 0.4, 'SSE was buffered')
        response.read()
        connection.close()

    def test_docker(self):
        self.check_config('docker/nginx.conf')

    def test_standalone(self):
        self.check_config('nginx.conf')


if __name__ == '__main__':
    unittest.main(verbosity=2)
