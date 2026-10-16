"""Read bounded recording windows without presenting archives as live telemetry."""
from collections import deque, OrderedDict
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time

NUMERIC_FIELDS = {
    't': ('t_s',), 'rpm': ('rpm',), 'curent': ('phase_current_a',),
    'rms': ('rms_est_a',), 'vdc': ('vdc_v',), 'frecventa': ('f_ref_hz',),
    'sincron': ('sync_rpm',), 'abatere': ('residual_rpm',),
    'abatere_pct': ('speed_error_pct',),
}


def finite_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def read_json(file_path):
    try:
        if file_path.stat().st_size > 128 * 1024:
            return {}
        result = json.loads(file_path.read_text(encoding='utf-8-sig'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(file_path, value):
    temporary = file_path.with_suffix(file_path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=True, allow_nan=False), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(file_path)
            return
        except PermissionError:
            time.sleep(0.02)
    temporary.replace(file_path)


def parse_sample(row):
    result = {}
    for key, columns in NUMERIC_FIELDS.items():
        result[key] = finite_number(next((row[name] for name in columns if name in row), None))
    result['stare'] = row.get('status') or 'NECUNOSCUTA'
    result['alarme'] = finite_number(row.get('active_alarm_count'))
    return result


def aggregate_points(points, limit):
    """Retain per-signal extrema, sample order, and the window endpoints.

    Uniform decimation could hide current peaks. Aggregation affects only the
    chart; Octave diagnostics use the original samples.
    """
    if len(points) <= limit:
        return points
    keys = [key for key in NUMERIC_FIELDS if key != 't']
    group_count = max(1, (limit - 2) // (2 * len(keys)))
    step_size = math.ceil(len(points) / group_count)
    indices = {0, len(points) - 1}
    for start in range(0, len(points), step_size):
        end = min(len(points), start + step_size)
        for key in keys:
            valid_indices = [index for index in range(start, end) if points[index].get(key) is not None]
            if valid_indices:
                indices.add(min(valid_indices, key=lambda index: points[index][key]))
                indices.add(max(valid_indices, key=lambda index: points[index][key]))
    return [points[index] for index in sorted(indices)]


class CsvReader:
    """Keep the read offset before an incomplete final row with bounded memory."""
    def __init__(self, file_path, limit=20000, load_tail=True):
        self.file_path = file_path
        self.rows = deque(maxlen=limit)
        self.offset = 0
        self.columns = []
        self.load_tail = load_tail
        self.truncated = False
        self.invalid_count = 0
        self.signature = None

    def actualizeaza(self):
        new_rows = []
        try:
            file_stats = self.file_path.stat()
            signature = (file_stats.st_size, file_stats.st_mtime_ns)
            if signature == self.signature:
                return new_rows
            if file_stats.st_size < self.offset:
                self.offset = 0
                self.rows.clear()
                self.columns = []
            with self.file_path.open('rb') as file:
                if not self.columns:
                    header = file.readline(16384)
                    if not header.endswith(b'\n'):
                        return new_rows
                    self.columns = next(csv.reader([header.decode('utf-8-sig').strip()]))
                    self.offset = file.tell()
                    if self.load_tail and file_stats.st_size - self.offset > 2 * 1024 * 1024:
                        file.seek(file_stats.st_size - 2 * 1024 * 1024)
                        file.readline(16384)
                        self.offset = file.tell()
                        self.truncated = True
                file.seek(self.offset)
                block = file.read(2 * 1024 * 1024)
            end = block.rfind(b'\n')
            if end < 0:
                if len(block) >= 16384:
                    self.offset += len(block)
                    self.invalid_count += 1
                return new_rows
            self.offset += end + 1
            for line in block[:end + 1].decode('utf-8', 'replace').splitlines():
                try:
                    values = next(csv.reader([line]))
                    if len(values) != len(self.columns):
                        self.invalid_count += 1
                        continue
                    row = dict(zip(self.columns, values))
                    if finite_number(row.get('t_s')) is None:
                        self.invalid_count += 1
                        continue
                    self.rows.append(row)
                    new_rows.append(row)
                except csv.Error:
                    self.invalid_count += 1
            # Continue on the next poll if the file exceeds one read block.
            self.signature = signature if self.offset >= file_stats.st_size else None
        except OSError:
            pass
        return new_rows


def alarm_quantity(code):
    if code.startswith('I_RMS'):
        return 'Curent RMS estimat [A]'
    if code.startswith('VDC') or code == 'START_BEFORE_READY':
        return 'DC-link [V]'
    if code.startswith('SPEED'):
        return 'Abatere fata de sincronism [%]'
    return 'Proces'


class DataStore:
    def __init__(self, settings, instance_id):
        self.settings = settings
        self.directory = Path(settings['director_rezultate'])
        self.instance_id = instance_id
        self.readers = OrderedDict()
        self.alarm_history = {}
        self.active = {}
        self.lock = threading.RLock()

    def sessions(self):
        sessions = []
        for file_path in self.directory.glob('*_samples.csv'):
            if file_path.is_symlink() or not file_path.is_file():
                continue
            name = file_path.name[:-12]
            if name.startswith(('drive_', 'psim_')):
                source = 'psim'
            else:
                continue
            try:
                sessions.append({'id': name, 'sursa': source, 'modificat_epoch': file_path.stat().st_mtime})
            except OSError:
                continue
        return sorted(sessions, key=lambda session: session['modificat_epoch'], reverse=True)

    def session_path(self, name, kind='samples'):
        if kind not in ('samples', 'events', 'meta') or not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
            return None
        file_path = self.directory / f'{name}_{kind}.{ "json" if kind == "meta" else "csv"}'
        if file_path.is_symlink() or not file_path.resolve().is_relative_to(self.directory):
            return None
        if not any(session['id'] == name for session in self.sessions()):
            return None
        return file_path

    def reader(self, file_path, events=False):
        if file_path not in self.readers:
            # Keep at most eight readers regardless of the number of archived files.
            while len(self.readers) >= 8:
                previous, _ = self.readers.popitem(last=False)
                self.alarm_history.pop(previous, None)
                self.active.pop(previous, None)
            self.readers[file_path] = CsvReader(file_path, 500 if events else 20000, not events)
        self.readers.move_to_end(file_path)
        return self.readers[file_path]

    def events(self, file_path):
        reader = self.reader(file_path, True)
        new_rows = reader.actualizeaza()
        active = self.active.setdefault(file_path, {})
        history = self.alarm_history.setdefault(file_path, deque(maxlen=200))
        for row in new_rows:
            code = row.get('code', '')
            nivel = row.get('level', '')
            if nivel in ('WARN', 'ALARM'):
                alarm = {'cod': code, 'severitate': nivel, 'activare_s': finite_number(row['t_s']), 'revenire_s': None,
                          'valoare': finite_number(row.get('value')), 'variabila': alarm_quantity(code)}
                active[code] = alarm
                history.append(alarm)
            elif nivel == 'CLEARED' and code in active:
                active.pop(code)['revenire_s'] = finite_number(row['t_s'])
        notifications = [{'t': finite_number(row['t_s']), 'nivel': row.get('level'), 'cod': row.get('code'), 'valoare': finite_number(row.get('value'))}
                      for row in reader.rows if row.get('level') in ('INFO', 'STATE')]
        return list(history), list(active.values()), notifications

    def recording(self, name, window_seconds=None):
        with self.lock:
            file_path = self.session_path(name)
            if file_path is None:
                return None
            reader = self.reader(file_path)
            reader.actualizeaza()
            points = []
            for row in reader.rows:
                point = parse_sample(row)
                if not points or point['t'] > points[-1]['t']:
                    points.append(point)
            latest = points[-1] if points else None
            if latest and window_seconds:
                points = [point for point in points if point['t'] >= latest['t'] - window_seconds]
            source = next(session['sursa'] for session in self.sessions() if session['id'] == name)
            history, active, notifications = self.events(file_path.with_name(name + '_events.csv'))
            meta = read_json(file_path.with_name(name + '_meta.json'))
            timestamp = file_path.stat().st_mtime
            event_log = [{'t': finite_number(row['t_s']), 'nivel': row.get('level'), 'cod': row.get('code'), 'valoare': finite_number(row.get('value'))}
                      for row in self.readers[file_path.with_name(name + '_events.csv')].rows]
            return {'id': name, 'sursa': source, 'context': 'inregistrare', 'achizitie': 'INREGISTRARE',
                    'vechime_s': max(0, time.time() - timestamp), 'inregistrat_utc': datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                    'ultim': latest, 'puncte': aggregate_points(points, self.settings['puncte_maxime']),
                    'alarme': active, 'istoric_alarme': history, 'evenimente': notifications,
                    'metadate': meta, 'fereastra_limitata': True, 'esantioane_recente': points[-50:], 'jurnal_evenimente': event_log,
                    'randuri_invalide': reader.invalid_count, 'are_evenimente': file_path.with_name(name + '_events.csv').is_file()}

    def live_source(self, source, window_seconds=None):
        with self.lock:
            snapshot = read_json(self.directory / f'stare_{source}.json')
            valid = snapshot.get('orchestrator_id') == self.instance_id and snapshot.get('sursa') == source
            timestamp = finite_number(snapshot.get('actualizat_epoch')) or 0
            fresh = valid and time.time() - timestamp <= self.settings['date_vechi_s']
            acquisition = snapshot.get('achizitie', 'OPRIT') if fresh else 'INDISPONIBIL'
            if acquisition == 'ACTIV' and time.time() - (finite_number(snapshot.get('esantion_epoch')) or 0) > self.settings['date_vechi_s']:
                acquisition = 'ASTEPTARE'
            name = snapshot.get('segment_id') if valid else None
            window_seconds = window_seconds or self.settings['fereastra_s']
            data = self.recording(name, window_seconds) if name else None
            if data and data['ultim'] and snapshot.get('schema') == 'industrial-drive.sesiune.v2':
                points = list(data['puncte'])
                minimum_time = data['ultim']['t'] - window_seconds
                part_index = int(name.rsplit('_part', 1)[-1])
                # Read only segments intersecting the window, capped at eight
                # segments and 20,000 samples even for long intervals.
                for index in range(part_index-1, max(0, part_index-8), -1):
                    previous = f'{snapshot["session_id"]}_part{index:04d}'
                    recording = self.recording(previous, window_seconds)
                    if not recording:
                        break
                    preceding_points = [point for point in recording['puncte'] if point['t'] >= minimum_time]
                    points = preceding_points + points
                    if not preceding_points or (preceding_points and preceding_points[0]['t'] <= minimum_time):
                        break
                data['puncte'] = aggregate_points(points[-20000:], self.settings['puncte_maxime'])
            if not data:
                data = {'id': None, 'sursa': source, 'ultim': None, 'puncte': [], 'alarme': [], 'istoric_alarme': [], 'evenimente': []}
            sample_time = finite_number(snapshot.get('esantion_epoch'))
            data.update(context='live', achizitie=acquisition, metadate=snapshot if valid else {},
                        vechime_s=max(0, time.time() - sample_time) if valid and sample_time else None)
            if acquisition != 'ACTIV':
                # The last sample remains available as history, not a live reading.
                data['ultim_cunoscut'] = data.get('ultim')
                data['ultim'] = None
            if fresh:
                data['alarme'] = snapshot.get('alarme_active', [])
            return data

    def psim_reception(self):
        transfer = read_json(self.directory / 'stare_receptie_psim.json')
        if transfer.get('orchestrator_id') != self.instance_id:
            return {'conectat': False, 'dll_hmi': False, 'cadre_valide': 0,
                    'cadre_respinse': 0, 'ultim_cadru': None, 'actual': False}
        timestamp = finite_number(transfer.get('actualizat_epoch')) or 0
        transfer['actual'] = 0 <= time.time() - timestamp <= self.settings['date_vechi_s']
        if not transfer['actual']:
            transfer.update(conectat=False, dll_hmi=False)
        sample_time = finite_number(transfer.get('esantion_epoch')) or 0
        transfer['vechime_s'] = max(0, time.time()-sample_time) if sample_time else None
        return transfer
