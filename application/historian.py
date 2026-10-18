"""Bounded, restartable SQLite index over the existing PSIM recordings.

The writer owns its connection in a background thread. Motor commands never
wait for SQLite. CSV remains the full-resolution archive and export format.
"""
from contextlib import closing
import csv
import hashlib
import json
import queue
import sqlite3
import threading
import time

from .data_store import finite_number, parse_sample, read_json

FIELDS = ('rpm', 'curent', 'rms', 'vdc', 'frecventa', 'sincron', 'abatere_pct')
UNITS = dict(zip(FIELDS, ('rpm', 'A', 'A', 'V', 'Hz', 'rpm', '%')))


def event_from_row(session_id, row, observed_epoch=None):
    identity = json.dumps([session_id, row.get('t_s'), row.get('level'), row.get('code'), row.get('value')], separators=(',', ':'))
    code, level = row.get('code', ''), row.get('level', 'INFO')
    return {'id': hashlib.sha256(identity.encode()).hexdigest(), 'session_id': session_id,
            'source': 'psim', 'origin': 'psim_simulation', 'sim_time_s': finite_number(row.get('t_s')),
            'observed_epoch': observed_epoch or time.time(), 'code': code,
            'severity': 'ALARM' if code == 'DRIVE_FAULT' or level == 'ALARM' else 'WARN' if level == 'WARN' else 'INFO',
            'level': level, 'value': finite_number(row.get('value'))}


def read_batch(path, offset, maximum=256 * 1024):
    """Return complete CSV records and an offset safe to commit transactionally."""
    with path.open('rb') as stream:
        header = stream.readline(16384)
        if not header.endswith(b'\n'):
            return [], offset
        columns = next(csv.reader([header.decode('utf-8-sig').strip()]))
        start = max(stream.tell(), offset)
        if path.stat().st_size < start:
            raise ValueError('Recording was truncated; existing history is preserved.')
        stream.seek(start)
        block = stream.read(maximum)
    end = block.rfind(b'\n')
    if end < 0:
        if len(block) == maximum:
            raise ValueError('Recording contains an oversized row.')
        return [], start
    rows = []
    for line in block[:end + 1].decode('utf-8', 'replace').splitlines():
        try:
            values = next(csv.reader([line]))
            row = dict(zip(columns, values))
            if len(values) == len(columns) and finite_number(row.get('t_s')) is not None:
                rows.append(row)
        except csv.Error:
            continue
    return rows, start + end + 1


class Historian:
    def __init__(self, settings, store, stop_event):
        self.settings = settings['iiot']['historian']
        self.store, self.stop_event = store, stop_event
        self.path = store.directory / 'historian.sqlite3'
        self.thread = None
        self.service_events = queue.Queue(maxsize=64)
        self.state = {'enabled': self.settings['enabled'], 'available': False, 'error': None, 'dropped_service_events': 0}
        self.position = 0
        self.last_retention = 0

    def connect_writer(self):
        connection = sqlite3.connect(self.path, timeout=0.2)
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=NORMAL')
            connection.execute('PRAGMA journal_size_limit=4194304')
            connection.execute(f'PRAGMA max_page_count={self.settings["max_size_mb"] * 1024 * 1024 // 4096}')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                connection.close()
                raise ValueError('Unsupported historian schema.')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, run_id TEXT, source TEXT, units TEXT);
                CREATE TABLE IF NOT EXISTS cursors(session_id TEXT, kind TEXT, offset INTEGER NOT NULL DEFAULT 0,
                    last_sim REAL, last_state TEXT, PRIMARY KEY(session_id, kind));
                CREATE TABLE IF NOT EXISTS samples(session_id TEXT, sim_time_s REAL, observed_epoch REAL,
                    rpm REAL, curent REAL, rms REAL, vdc REAL, frecventa REAL, sincron REAL, abatere_pct REAL,
                    state TEXT, PRIMARY KEY(session_id, sim_time_s));
                CREATE INDEX IF NOT EXISTS samples_wall_time ON samples(observed_epoch);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE,
                    session_id TEXT, sim_time_s REAL, observed_epoch REAL, source TEXT, origin TEXT,
                    code TEXT, severity TEXT, level TEXT, value REAL);
                CREATE INDEX IF NOT EXISTS events_session_time ON events(session_id, sim_time_s);
                CREATE INDEX IF NOT EXISTS events_wall_time ON events(observed_epoch);
                PRAGMA user_version=1;
            ''')
            return connection
        except (sqlite3.Error, OSError, ValueError):
            connection.close()
            raise

    def ingest(self, connection, session):
        name = session['id']
        meta = read_json(self.store.directory / f'{name}_meta.json')
        with connection:
            connection.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)',
                               (name, meta.get('session_id', name), 'psim', json.dumps(UNITS)))
            for kind in ('samples', 'events'):
                path = self.store.directory / f'{name}_{kind}.csv'
                if path.is_symlink() or not path.is_file():
                    continue
                cursor = connection.execute('SELECT offset,last_sim,last_state FROM cursors WHERE session_id=? AND kind=?', (name, kind)).fetchone()
                offset, last_sim, last_state = cursor or (0, None, None)
                rows, end = read_batch(path, offset)
                if kind == 'samples':
                    for row in rows:
                        point = parse_sample(row)
                        t = point['t']
                        if t < 0 or last_sim is not None and t < last_sim:
                            continue
                        if last_sim is None or t - last_sim >= self.settings['sample_interval_s'] - 1e-9 or point['stare'] != last_state:
                            connection.execute('INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (name, t, time.time(), *(point[key] for key in FIELDS), point['stare']))
                            last_sim, last_state = t, point['stare']
                else:
                    for row in rows:
                        event = event_from_row(name, row)
                        connection.execute('INSERT OR IGNORE INTO events(id,session_id,sim_time_s,observed_epoch,source,origin,code,severity,level,value) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                           tuple(event[key] for key in ('id','session_id','sim_time_s','observed_epoch','source','origin','code','severity','level','value')))
                connection.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?,?,?)', (name, kind, end, last_sim, last_state))

    def retain(self, connection):
        cutoff = time.time() - self.settings['retention_days'] * 86400
        with connection:
            for table, column, limit in (('samples', 'observed_epoch', 'max_sample_rows'), ('events', 'observed_epoch', 'max_event_rows')):
                connection.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE {column} < ? LIMIT 10000)', (cutoff,))
                count = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                overflow = min(10000, max(0, count - self.settings[limit]))
                if overflow:
                    connection.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY {column} LIMIT ?)', (overflow,))
            existing = {session['id'] for session in self.store.sessions()}
            for (name,) in connection.execute('SELECT id FROM sessions'):
                if name not in existing:
                    connection.execute('DELETE FROM cursors WHERE session_id=?', (name,))
                    connection.execute('DELETE FROM sessions WHERE id=? AND NOT EXISTS(SELECT 1 FROM samples WHERE session_id=?) AND NOT EXISTS(SELECT 1 FROM events WHERE session_id=?)', (name, name, name))
        connection.execute('PRAGMA wal_checkpoint(PASSIVE)')

    def poll(self, connection):
        sessions = self.store.sessions()
        if sessions:
            self.position %= len(sessions)
            selected = (sessions[self.position:] + sessions[:self.position])[:8]
            self.position += len(selected)
            for session in selected:
                self.ingest(connection, session)
        with connection:
            for _ in range(64):
                try:
                    event = self.service_events.get_nowait()
                except queue.Empty:
                    break
                connection.execute('INSERT OR IGNORE INTO events(id,session_id,sim_time_s,observed_epoch,source,origin,code,severity,level,value) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    tuple(event.get(key) for key in ('id','session_id','sim_time_s','observed_epoch','source','origin','code','severity','level','value')))
        if time.monotonic() - self.last_retention >= 30:
            self.retain(connection)
            self.last_retention = time.monotonic()

    def enqueue_event(self, event):
        if self.settings['enabled']:
            try:
                self.service_events.put_nowait(dict(event))
            except queue.Full:
                self.state['dropped_service_events'] += 1

    def run(self):
        connection = None
        try:
            while not self.stop_event.is_set():
                try:
                    if connection is None:
                        connection = self.connect_writer()
                    self.poll(connection)
                    self.state.update(available=True, error=None)
                    self.stop_event.wait(0.5)
                except (sqlite3.Error, OSError, ValueError) as error:
                    self.state.update(available=False, error=type(error).__name__)
                    if connection:
                        connection.close()
                        connection = None
                    self.stop_event.wait(5)
        finally:
            if connection:
                connection.close()

    def start(self):
        if self.settings['enabled']:
            self.thread = threading.Thread(target=self.run, name='sqlite-historian', daemon=True)
            self.thread.start()

    def close(self):
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                return
        if self.settings['enabled']:
            try:
                with closing(self.connect_writer()) as connection:
                    self.poll(connection)
                    # The Octave process has stopped and flushed its final rows.
                    for session in self.store.sessions()[:8]:
                        self.ingest(connection, session)
            except (sqlite3.Error, OSError, ValueError) as error:
                self.state.update(available=False, error=type(error).__name__)

    def reader(self):
        if not self.settings['enabled'] or not self.path.is_file():
            raise OSError('Historian unavailable.')
        connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        return connection

    def sessions(self):
        with closing(self.reader()) as connection:
            return [dict(row) for row in connection.execute('''SELECT s.id,s.run_id,s.source,COUNT(*) AS sample_count,
                MIN(m.sim_time_s) AS start_s,MAX(m.sim_time_s) AS end_s,MAX(m.observed_epoch) AS observed_epoch
                FROM sessions s JOIN samples m ON m.session_id=s.id GROUP BY s.id
                ORDER BY observed_epoch DESC LIMIT 200''')]

    def query_events(self, source='', start=0, end=1e12, after=0, limit=100):
        if not isinstance(source, str) or len(source) > 128 or any(finite_number(value) is None for value in (start, end)) or start > end or not 0 <= after <= 2**63-1 or not 1 <= limit <= 500:
            raise ValueError('Invalid event query.')
        with closing(self.reader()) as connection:
            rows = [dict(row) for row in connection.execute('SELECT * FROM events WHERE (?=\'\' OR source=?) AND observed_epoch BETWEEN ? AND ? AND seq>? ORDER BY seq LIMIT ?',
                (source, source, start, end, after, limit + 1))]
            return {'context': 'history', 'events': rows[:limit], 'next_after': rows[limit-1]['seq'] if len(rows) > limit else None}

    def query(self, session, start=0, end=1e12, axis='simulation', limit=1000, after=-1):
        if axis not in ('simulation', 'observed') or not isinstance(session, str) or len(session) > 200:
            raise ValueError('Invalid history query.')
        if any(finite_number(value) is None for value in (start, end, after)) or start > end or not 1 <= limit <= 1000:
            raise ValueError('Invalid history interval.')
        column = 'sim_time_s' if axis == 'simulation' else 'observed_epoch'
        where = f'session_id=? AND {column}>=? AND {column}<=?'
        args = (session, start, end)
        with closing(self.reader()) as connection:
            stats = {}
            for field in FIELDS:
                stats[field] = dict(connection.execute(f'SELECT MIN({field}) AS minimum,MAX({field}) AS maximum,AVG({field}) AS average FROM samples WHERE {where}', args).fetchone())
            count = connection.execute(f'SELECT COUNT(*) FROM samples WHERE {where}', args).fetchone()[0]
            rows = [dict(row) for row in connection.execute(f'SELECT rowid AS sample_id,* FROM samples WHERE {where} AND rowid>? ORDER BY rowid LIMIT ?', (*args, after, limit + 1))]
            events = [dict(row) for row in connection.execute(f'SELECT * FROM events WHERE {where} ORDER BY seq LIMIT 100', args)]
            return {'session_id': session, 'source': 'psim', 'origin': 'psim_simulation', 'context': 'history',
                    'time_axis': axis, 'units': UNITS, 'sample_count': count, 'statistics': stats,
                    'samples': rows[:limit], 'events': events, 'events_limited': len(events) == 100,
                    'next_after': rows[limit-1]['sample_id'] if len(rows) > limit else None}
