"""Exercise Octave and Mosquitto with data generated inside the isolated test."""
import csv
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from application.config import PROJECT_ROOT, find_executable
from application.services import check_broker


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def wait_for(condition, limit=20):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            result = condition()
            if result:
                return result
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise AssertionError('Conditia de integrare nu a fost indeplinita in termen.')


def main():
    import paho.mqtt.client as mqtt
    settings = json.loads((PROJECT_ROOT / 'config/app_config.json').read_text())
    settings['port_web'] = free_port()
    settings['psim']['port_tcp'] = free_port()
    settings['mqtt']['port'] = free_port()
    settings['mqtt']['prefix'] = 'industrial-drive/verificare'
    settings['psim']['segment_s'] = 5
    settings['deschide_browser'] = False
    broker_executable = find_executable('', 'mosquitto', ['Mosquitto/mosquitto.exe'])
    assert broker_executable, 'Mosquitto este necesar acestei verificari.'
    processes = []
    client = None
    with tempfile.TemporaryDirectory(prefix='verificare_', dir=PROJECT_ROOT / 'results') as temporary:
        directory = Path(temporary)
        settings['director_rezultate'] = str(directory / 'date')
        config_path = directory / 'configuratie.json'
        config_path.write_text(json.dumps(settings))
        broker_config_path = directory / 'mosquitto.conf'
        broker_config_path.write_text(f'listener {settings["mqtt"]["port"]} 127.0.0.1\nallow_anonymous true\npersistence false\n')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        try:
            # This test owns the broker process; the orchestrator does not.
            broker = subprocess.Popen([broker_executable, '-c', str(broker_config_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            processes.append(broker)
            wait_for(lambda: check_broker('127.0.0.1', settings['mqtt']['port']) == 'MQTT')
            messages = []
            lock = threading.Lock()
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            def on_connect(client, userdata, flags, reason_code, properties):
                client.subscribe('industrial-drive/verificare/#')
            def on_message(client, userdata, message):
                with lock:
                    messages.append((message.topic, json.loads(message.payload)))
            client.on_connect = on_connect
            client.on_message = on_message
            client.connect('127.0.0.1', settings['mqtt']['port'])
            client.loop_start()
            event_log = (directory / 'jurnal.log').open('wb')
            process = subprocess.Popen([sys.executable, str(PROJECT_ROOT / 'orchestrator.py'), '--config', str(config_path), '--fara-browser'], cwd=PROJECT_ROOT, stdout=event_log, stderr=subprocess.STDOUT, **options)
            processes.append(process)
            base_url = f'http://127.0.0.1:{settings["port_web"]}'
            def read(file_path):
                return json.load(urllib.request.urlopen(base_url + file_path, timeout=3))
            system = wait_for(lambda: (data if (data := read('/api/stare'))['receptie']['actual'] and data['psim']['achizitie'] == 'ASTEPTARE' else None))
            assert system['psim']['ultim'] is None and system['psim']['achizitie'] == 'ASTEPTARE'
            assert 'model' not in system and 'model' not in system['control']
            assert system['control']['psim']['aplicat']['ack_epoch'] == 0
            time.sleep(1)
            assert not list((directory / 'date').glob('model_*')), 'Octave a generat o simulare independenta.'
            assert system['servicii']['broker']['activ'] is False
            assert 'Broker existent' in system['servicii']['broker']['mesaj']
            second = subprocess.run([sys.executable, str(PROJECT_ROOT / 'orchestrator.py'), '--config', str(config_path), '--fara-browser'], capture_output=True, timeout=5, **options)
            assert second.returncode == 2 and b'deja pornita' in second.stderr
            # Deterministic transport data stays within this test. User archives
            # are neither required nor recreated.
            rows = []
            for index in range(2501):
                sample_time = index/1000
                frequency = max(0, min(50, (sample_time-0.32)*50))
                rows.append({'t_s': f'{sample_time:.6f}', 'rpm': f'{30*frequency:.6f}',
                    'phase_current_a': '1.25', 'vdc_v': '565.5', 'f_ref_hz': f'{frequency:.6f}'})
            payload = ''.join(','.join(row[key] for key in ('t_s', 'rpm', 'phase_current_a', 'vdc_v', 'f_ref_hz')) + '\n' for row in rows).encode('ascii')
            with socket.create_connection(('127.0.0.1', settings['psim']['port_tcp'])) as connection:
                # Fragmentation verifies that TCP does not deliver atomic rows.
                connection.sendall(b'invalid\n')
                for offset in range(0, len(payload), 3000):
                    connection.sendall(payload[offset:offset+3000])
                    time.sleep(0.01)
                system = wait_for(lambda: (data if (data := read('/api/stare'))['psim']['ultim'] and data['receptie']['cadre_valide'] == len(rows) else None))
                assert system['psim']['ultim']['stare'] == 'RUNNING'
                assert system['receptie']['cadre_respinse'] == 1
                assert system['receptie']['cadre_valide'] == len(rows)
                assert system['receptie']['conectat'] is True and system['receptie']['dll_hmi'] is False
                raw = system['receptie']['ultim_cadru']
                for key in ('t_s', 'rpm', 'phase_current_a', 'vdc_v', 'f_ref_hz'):
                    assert raw[key] == float(rows[-1][key]), (key, raw[key], rows[-1][key])
                first_session = system['psim']['id']
                wait_for(lambda: any(topic.endswith('psim/telemetrie') for topic, _ in messages))
                connection.sendall(payload)
                wait_for(lambda: (data if (data := read('/api/stare'))['psim']['id'] != first_session and data['psim'].get('ultim') and data['receptie']['cadre_valide'] == 2*len(rows) else None))
                assert read('/api/stare')['receptie']['cadre_valide'] == 2*len(rows)
            wait_for(lambda: (data := read('/api/stare'))['psim']['achizitie'] == 'ASTEPTARE' and not data['receptie']['conectat'])
            system = read('/api/stare')
            assert system['psim']['ultim'] is None
            assert system['receptie']['conectat'] is False
            assert system['receptie']['ultim_cadru'] == raw, 'Cadrul brut trebuie pastrat dupa rulare.'
            inregistrari = read('/api/sesiuni')['sesiuni']
            recording = next(session['id'] for session in inregistrari if session['sursa'] == 'psim')
            data = read('/api/inregistrare?sesiune=' + recording)
            assert data['context'] == 'inregistrare' and data['achizitie'] == 'INREGISTRARE'
            assert all(s['sursa'] == 'psim' for s in inregistrari)
            with urllib.request.urlopen(base_url+'/api/export?sesiune='+recording+'&tip=samples') as response:
                export = list(csv.DictReader(response.read().decode().splitlines()))
            assert len(export) == len(rows)
            for row, original in zip(export, rows):
                for key in ('t_s', 'rpm', 'phase_current_a', 'vdc_v', 'f_ref_hz'):
                    assert abs(float(row[key])-float(original[key])) < 1e-5
            for file_path in ('/api/comparatie', '/api/export?sesiune=..%2FREADME&tip=samples', '/api/export?sesiune='+recording+'&tip=meta'):
                try:
                    urllib.request.urlopen(base_url + file_path)
                    raise AssertionError('Exportul nepermis a fost acceptat.')
                except urllib.error.HTTPError as error:
                    assert error.code == 404
            for topic, payload in messages:
                if topic.endswith('/telemetrie'):
                    assert payload['context'] == 'live' and payload['sursa'] == 'psim'
            assert not list((directory/'date').glob('model_*'))
            runtime = json.loads((PROJECT_ROOT / '.runtime.json').read_text())
            Path(runtime['fisier_oprire']).touch()
            assert process.wait(timeout=10) == 0
            event_log.close()
            assert broker.poll() is None, 'Orchestratorul a oprit brokerul extern.'
            for port in (settings['port_web'], settings['psim']['port_tcp']):
                with socket.socket() as check:
                    assert check.connect_ex(('127.0.0.1', port)) != 0
            for file_path in (directory / 'date').glob('*_meta.json'):
                assert json.loads(file_path.read_text())['achizitie'] in ('OPRIT', 'INREGISTRARE')
            print('Integrare reusita: PSIM exclusiv, asteptare fara date fabricate, TCP fragmentat/reset, cadre brute/CSV identice, retrait live, MQTT PSIM, broker extern pastrat si oprire controlata. Replay izolat; nu rulare nativa PSIM.')
        finally:
            if 'process' in locals() and process.poll() is None:
                runtime = json.loads((PROJECT_ROOT / '.runtime.json').read_text())
                Path(runtime['fisier_oprire']).touch()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            if client:
                client.disconnect()
                client.loop_stop()
            for owned_process in reversed(processes):
                if owned_process.poll() is None:
                    owned_process.terminate()
                    owned_process.wait(timeout=5)
            time.sleep(0.2)
            if 'event_log' in locals() and not event_log.closed:
                event_log.close()


if __name__ == '__main__':
    main()
