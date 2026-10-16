"""Serve the local HMI and API while GNU Octave owns numerical processing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DASHBOARD_DIR = Path(__file__).resolve().parent


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


class HMIRequestHandler(BaseHTTPRequestHandler):
    server_version = 'IndustrialDrive/2'

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.valid_host():
            return self.respond({'mesaj': 'Gazda nepermisa.'}, 403)
        request = urlsplit(self.path)
        params = parse_qs(request.query)
        file_path = request.path
        store = self.server.store
        if file_path == '/api/stare':
            try:
                window_seconds = max(0.1, min(86400, float((params.get('fereastra') or [store.settings['fereastra_s']])[0])))
            except ValueError:
                window_seconds = store.settings['fereastra_s']
            return self.respond({'servicii': self.server.servicii.state(), 'mqtt': self.server.mqtt.state,
                'psim': store.live_source('psim', window_seconds), 'receptie': store.psim_reception(),
                'control': self.server.servicii.control.state(self.server.servicii.state().get('octave', {}).get('activ', False))})
        if file_path == '/api/sesiuni':
            return self.respond({'sesiuni': [s for s in store.sessions() if s['sursa'] == 'psim']})
        if file_path == '/api/inregistrare':
            name = (params.get('sesiune') or [''])[0]
            try:
                window_seconds = float((params.get('fereastra') or [store.settings['fereastra_s']])[0])
            except ValueError:
                window_seconds = store.settings['fereastra_s']
            window_seconds = max(0.1, min(86400, window_seconds))
            result = store.recording(name, window_seconds)
            if result and result['sursa'] != 'psim':
                result = None
            return self.respond(result or {'mesaj': 'Rezultat indisponibil.'}, 200 if result else 404)
        if file_path == '/api/export':
            name = (params.get('sesiune') or [''])[0]
            kind = (params.get('tip') or [''])[0]
            psim = any(s['id'] == name and s['sursa'] == 'psim' for s in store.sessions())
            file = store.session_path(name, kind) if psim and kind in ('samples', 'events') else None
            if file is None or not file.is_file():
                return self.respond({'mesaj': 'Fisier indisponibil.'}, 404)
            try:
                with file.open('rb') as content:
                    length = file.stat().st_size
                    self.send_headers(200, 'text/csv; charset=utf-8', length, file.name)
                    remaining = length
                    while remaining > 0:
                        block = content.read(min(remaining, 65536))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (OSError, ConnectionError):
                pass
            return
        static_files = {'/': ('index.html', 'text/html'), '/app.css': ('app.css', 'text/css'),
                   '/app.js': ('app.js', 'text/javascript'), '/charts.js': ('charts.js', 'text/javascript')}
        if file_path not in static_files:
            return self.respond({'mesaj': 'Resursa inexistenta.'}, 404)
        name, kind = static_files[file_path]
        content = (DASHBOARD_DIR / name).read_bytes()
        self.send_headers(200, kind + '; charset=utf-8', len(content))
        self.wfile.write(content)

    def do_POST(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if not self.valid_host() or self.headers.get('Origin', origin) != origin or self.headers.get('Content-Type') != 'application/json':
            return self.respond({'mesaj': 'Origine sau tip de cerere nepermis.'}, 403)
        if self.path != '/api/control':
            return self.respond({'mesaj': 'Operatie inexistenta.'}, 404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 2048:
                raise ValueError()
            request = json.loads(self.rfile.read(length))
            active = self.server.servicii.state().get('octave', {}).get('activ', False)
            response, code = self.server.servicii.control.submit(request, active)
            return self.respond(response, code)
        except (ValueError, AttributeError):
            return self.respond({'mesaj': 'Cerere invalida.'}, 400)

    def send_headers(self, code, kind, length, download_name=None):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if download_name:
            self.send_header('Content-Disposition', f'attachment; filename="{download_name}"')
        self.end_headers()

    def respond(self, value, code=200):
        content = json.dumps(value, allow_nan=False).encode('utf-8')
        self.send_headers(code, 'application/json; charset=utf-8', len(content))
        try:
            self.wfile.write(content)
        except ConnectionError:
            pass

    def log_message(self, format, *args):
        pass
