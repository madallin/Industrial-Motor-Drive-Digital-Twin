"""Serve the local HMI and API while GNU Octave owns numerical processing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from application.telemetry import system_snapshot
from .stream import serve_stream

DASHBOARD_DIR = Path(__file__).resolve().parent


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


class HMIRequestHandler(BaseHTTPRequestHandler):
    server_version = 'IndustrialDrive/2'
    rbufsize = 0

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
        if file_path == '/api/stream':
            try:
                window = float((params.get('fereastra') or [store.settings['fereastra_s']])[0])
                if not 0.1 <= window <= 86400:
                    raise ValueError()
            except ValueError:
                return self.respond({'mesaj': 'Interval invalid.'}, 400)
            return serve_stream(self, window)
        if file_path.startswith('/api/historian/'):
            try:
                historian = self.server.historian
                if file_path == '/api/historian/sessions':
                    return self.respond({'sessions': historian.sessions(), 'status': historian.state})
                if file_path == '/api/historian/events':
                    value = lambda name, default: (params.get(name) or [default])[0]
                    return self.respond(historian.query_events(value('source', ''), float(value('start', 0)),
                        float(value('end', 1e12)), int(value('after', 0)), int(value('limit', 100))))
                if file_path == '/api/historian/query':
                    value = lambda name, default: (params.get(name) or [default])[0]
                    return self.respond(historian.query(value('session', ''), float(value('start', 0)),
                        float(value('end', 1e12)), value('axis', 'simulation'), int(value('limit', 1000)), float(value('after', -1))))
            except (OSError, sqlite3.Error):
                return self.respond({'mesaj': 'Istoricul structurat nu este disponibil.'}, 503)
            except (ValueError, TypeError):
                return self.respond({'mesaj': 'Interval istoric invalid.'}, 400)
            return self.respond({'mesaj': 'Resursa inexistenta.'}, 404)
        if file_path == '/api/stare':
            try:
                window_seconds = max(0.1, min(86400, float((params.get('fereastra') or [store.settings['fereastra_s']])[0])))
            except ValueError:
                window_seconds = store.settings['fereastra_s']
            return self.respond(system_snapshot(self.server, window_seconds))
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
                   '/app.js': ('app.js', 'text/javascript'), '/charts.js': ('charts.js', 'text/javascript'),
                   '/transport.js': ('transport.js', 'text/javascript'), '/iiot.js': ('iiot.js', 'text/javascript')}
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
        if self.path not in ('/api/control', '/api/notifications/ack'):
            return self.respond({'mesaj': 'Operatie inexistenta.'}, 404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 2048:
                raise ValueError()
            request = json.loads(self.rfile.read(length))
            if self.path == '/api/notifications/ack':
                if not isinstance(request, dict) or set(request) != {'id'} or not isinstance(request['id'], str):
                    raise ValueError()
                acknowledged = self.server.mqtt_consumer.notifications.acknowledge(request['id'])
                return self.respond({'acknowledged': acknowledged}, 200 if acknowledged else 404)
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
        self.send_header('Content-Security-Policy', f"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self' ws://127.0.0.1:{self.server.server_port}; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
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
