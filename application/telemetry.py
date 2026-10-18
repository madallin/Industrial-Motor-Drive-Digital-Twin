"""Read-only snapshots and ordered events shared by HTTP, WebSocket, and MQTT."""
from collections import OrderedDict, deque
import socket
import re
import threading
import time
import uuid

from .historian import event_from_row, read_batch
from .data_store import read_json


def segment_order(session):
    name = session['id']
    match = re.fullmatch(r'(.*_\d{8}_\d{6})_(\d+)_part(\d+)', name)
    if match:
        return match[1], int(match[2]), int(match[3])
    run, marker, part = name.rpartition('_part')
    return (run, 0, int(part)) if marker and part.isdigit() else (name, 0, 0)


def system_snapshot(server, window_seconds=None):
    services = server.servicii.state()
    result = {'servicii': services, 'mqtt': dict(server.mqtt.state),
              'psim': server.store.live_source('psim', window_seconds),
              'receptie': server.store.psim_reception(),
              'control': server.servicii.control.state(services.get('octave', {}).get('activ', False))}
    result['iiot'] = {'historian': dict(server.historian.state)}
    if getattr(server, 'mqtt_consumer', None):
        result['iiot'].update(server.mqtt_consumer.state())
    return result


class TelemetryHub:
    """One replaceable snapshot slot; a bounded event journal per application.

    Slow clients skip obsolete snapshots. They never silently skip events: a
    journal overrun requires resynchronization. Socket writes have a deadline
    enforced by this independent producer, including writes blocked in the OS.
    """
    def __init__(self, server, stop_event):
        self.server, self.stop_event = server, stop_event
        self.settings = server.store.settings['iiot']['websocket']
        self.events = deque(maxlen=self.settings['event_buffer'])
        self.seen = OrderedDict()
        self.offsets = OrderedDict()
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(self.settings['max_clients'])
        self.clients = {}
        self.windows = {}
        self.latest, self.epoch, self.revision, self.sequence = None, 0, 0, 0
        self.thread = None
        self.previous_acquisition = None
        self.error = None

    def add_event(self, event):
        with self.lock:
            if event['id'] in self.seen:
                return
            self.seen[event['id']] = True
            while len(self.seen) > self.settings['event_buffer'] * 4:
                self.seen.popitem(last=False)
            self.sequence += 1
            self.events.append(dict(event, schema='industrial-drive.event.v1', sequence=self.sequence))
            if event.get('origin') == 'service':
                self.server.historian.enqueue_event(event)

    def since(self, cursor=None, limit=64):
        with self.lock:
            if cursor is None:
                cursor = max(0, self.sequence - 50)
            gap = bool(self.events and cursor < self.events[0]['sequence'] - 1)
            events = [dict(event) for event in self.events if event['sequence'] > cursor][:limit]
            return events, gap

    def event_gap(self, identifier):
        self.add_event({'id': uuid.uuid4().hex, 'session_id': identifier, 'source': 'psim',
            'origin': 'service', 'sim_time_s': None, 'observed_epoch': time.time(),
            'severity': 'WARN', 'level': 'WARN', 'code': 'EVENT_JOURNAL_GAP', 'value': None})

    def read_events(self):
        # Discover files independently of live status: a fast or short PSIM run
        # may finish completely between two wall-clock publication ticks.
        sessions = self.server.store.sessions()
        selected = sessions[:4096]
        if len(sessions) > len(selected) and not getattr(self, 'catalog_limited', False):
            self.event_gap(None)
        self.catalog_limited = len(sessions) > len(selected)
        names = {session['id'] for session in selected}
        for name in list(self.offsets):
            if name not in names:
                self.offsets.pop(name)
        budget = 8
        for session in sorted(selected, key=segment_order):
            name = session['id']
            cursor = self.offsets.setdefault(name, {'offset': 0, 'signature': None, 'current': None})
            if cursor['current'] is None:
                meta = read_json(self.server.store.directory / f'{name}_meta.json')
                if not meta:
                    continue
                cursor['current'] = meta.get('orchestrator_id') == self.server.store.instance_id
            if not cursor['current']:
                continue
            path = self.server.store.session_path(name, 'events')
            if not path or not path.is_file():
                continue
            stats = path.stat()
            signature = (stats.st_size, stats.st_mtime_ns)
            if cursor['signature'] == signature:
                continue
            try:
                rows, end = read_batch(path, cursor['offset'])
                for row in rows:
                    self.add_event(event_from_row(name, row))
                cursor['offset'] = end
                cursor['signature'] = signature if end >= stats.st_size else None
                if end < stats.st_size:
                    # Finish this segment before emitting a later segment's
                    # events, even if a large event file needs several ticks.
                    break
            except ValueError:
                self.event_gap(name)
                cursor['signature'] = signature
            budget -= 1
            if not budget:
                break

    def tick(self):
        # Shutdown doesn't acquire the protocol lock held by a blocked writer.
        with self.lock:
            expired = [sock for sock, started in self.clients.items() if started and time.monotonic() - started > self.settings['send_timeout_s']]
        for sock in expired:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self.lock:
            window = max([self.server.store.settings['fereastra_s'], *self.windows.values()])
        snapshot = system_snapshot(self.server, window)
        self.read_events()
        acquisition = snapshot['psim']['achizitie']
        if acquisition != self.previous_acquisition and self.previous_acquisition is not None:
            lost = self.previous_acquisition == 'ACTIV' and acquisition != 'ACTIV'
            self.add_event({'id': uuid.uuid4().hex, 'session_id': snapshot['psim'].get('id'),
                'source': 'psim', 'origin': 'psim_simulation', 'sim_time_s': None,
                'observed_epoch': time.time(), 'severity': 'WARN' if lost else 'INFO',
                'level': 'WARN' if lost else 'INFO', 'code': 'COMMUNICATION_LOST' if lost else 'ACQUISITION_' + acquisition, 'value': None})
        self.previous_acquisition = acquisition
        with self.lock:
            self.latest, self.epoch = snapshot, time.time()
            self.revision += 1

    def frame(self, cursor, previous_revision, window_seconds):
        with self.lock:
            if self.latest is None:
                return None
            events, gap = self.since(cursor)
            system = dict(self.latest)
            data = system['psim'] = dict(system['psim'])
            points = data.get('puncte', [])
            if points:
                data['puncte'] = [point for point in points if point['t'] >= points[-1]['t'] - window_seconds]
            return {'schema': 'industrial-drive.stream.v1', 'snapshot_epoch': self.epoch,
                    'instance_id': self.server.store.instance_id,
                    'revision': self.revision, 'system': system, 'events': events, 'event_gap': gap,
                    'cursor': events[-1]['sequence'] if events else self.sequence if cursor is None else cursor,
                    'telemetry_skipped': max(0, self.revision - previous_revision - 1) if previous_revision else 0}

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.error = None
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.error = type(error).__name__
            self.stop_event.wait(self.settings['interval_s'])

    def start(self):
        self.thread = threading.Thread(target=self.run, name='telemetry-hub', daemon=True)
        self.thread.start()

    def close(self):
        with self.lock:
            sockets = list(self.clients)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=2)
