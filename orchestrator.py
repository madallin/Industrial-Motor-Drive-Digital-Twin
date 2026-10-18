"""Start and stop the local application and its owned services."""
import argparse
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid
import webbrowser

from application.config import PROJECT_ROOT, load_config
from application.data_store import DataStore, read_json, write_json
from application.services import ServiceManager
from application.recording_retention import enforce_recording_quota
from application.historian import Historian
from application.telemetry import TelemetryHub
from application.windows_processes import acquire_instance_lock
from dashboard.server import HMIRequestHandler, LocalServer
from mqtt.publisher import MQTTPublisher
from mqtt.consumer import MQTTConsumer

STATE_FILE = PROJECT_ROOT / '.runtime.json'


def request_shutdown():
    state = read_json(STATE_FILE)
    file_path = Path(state.get('fisier_oprire', ''))
    if not state or not file_path.is_absolute() or not file_path.resolve().is_relative_to(PROJECT_ROOT) or file_path.name != 'oprire.flag':
        print('Nu exista un orchestrator identificat pentru acest proiect.')
        return 1
    file_path.touch()
    print('Cererea de oprire controlata a fost transmisa orchestratorului.')
    return 0


def prune_new_recordings(settings, store):
    days = settings['retentie_zile']
    if not days:
        return
    cutoff = time.time() - days * 86400
    for session in store.sessions():
        name = session['id']
        meta = read_json(store.directory / f'{name}_meta.json')
        # Retention applies only to finalized v2 recordings; legacy files are untouched.
        if meta.get('schema') != 'industrial-drive.sesiune.v2' or meta.get('achizitie') not in ('OPRIT', 'INREGISTRARE'):
            continue
        if meta.get('actualizat_epoch', time.time()) >= cutoff:
            continue
        for suffix in ('_samples.csv', '_events.csv', '_meta.json'):
            file_path = store.directory / (name + suffix)
            if not file_path.is_symlink() and file_path.resolve().is_relative_to(store.directory):
                file_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Pornire centralizata Industrial Drive Digital Twin')
    parser.add_argument('--stop', action='store_true', help='Solicita oprirea proceselor proprii.')
    parser.add_argument('--config', type=Path, help='Configuratie JSON pentru operare sau verificare.')
    parser.add_argument('--fara-browser', action='store_true')
    options = parser.parse_args()
    if options.stop:
        return request_shutdown()
    try:
        settings = load_config(options.config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Configuratie invalida: {error}', file=sys.stderr)
        return 2
    try:
        instance_lock = acquire_instance_lock(PROJECT_ROOT / '.orchestrator.lock')
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        server = LocalServer(('127.0.0.1', settings['port_web']), HMIRequestHandler)
    except OSError:
        print(f'Portul web {settings["port_web"]} este ocupat. Verificati instanta existenta sau configuratia.', file=sys.stderr)
        instance_lock.close()
        return 2
    instance_id = uuid.uuid4().hex
    directory = Path(settings['director_rezultate'])
    directory.mkdir(parents=True, exist_ok=True)
    runtime_dir = directory / 'runtime' / instance_id
    runtime_dir.mkdir(parents=True)
    settings['orchestrator_id'] = instance_id
    settings['fisier_oprire'] = str(runtime_dir / 'oprire.flag')
    stop_event = threading.Event()
    store = DataStore(settings, instance_id)
    historian = Historian(settings, store, stop_event)
    servicii = ServiceManager(settings, store, runtime_dir, stop_event)
    mqtt = MQTTPublisher(settings['mqtt'], store, stop_event)
    server.store = store
    server.servicii = servicii
    server.mqtt = mqtt
    server.historian = historian
    consumer = MQTTConsumer(settings, stop_event, historian.enqueue_event)
    server.mqtt_consumer = consumer
    telemetry = TelemetryHub(server, stop_event)
    server.telemetry = telemetry
    mqtt.events = telemetry
    def on_signal(signal_number, frame):
        stop_event.set()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, on_signal)
    web_thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.25}, daemon=True)
    url = f'http://127.0.0.1:{settings["port_web"]}'
    try:
        write_json(STATE_FILE, {'pid': os.getpid(), 'id': instance_id, 'fisier_oprire': settings['fisier_oprire'], 'url': url})
        lease_path = runtime_dir / 'backend_lease.json'
        write_json(lease_path, {'orchestrator_id': instance_id, 'epoch': time.time()})
        prune_new_recordings(settings, store)
        servicii.start()
        mqtt.start()
        historian.start()
        consumer.start()
        telemetry.start()
        web_thread.start()
        print(f'HMI: {url}\nOprire: Ctrl+C sau stop.bat. PSIM se porneste manual cu F8.', flush=True)
        if settings['deschide_browser'] and not options.fara_browser:
            webbrowser.open(url)
        last_quota_check = 0
        while not stop_event.wait(0.5):
            write_json(lease_path, {'orchestrator_id': instance_id, 'epoch': time.time()})
            servicii.monitor()
            if time.monotonic() - last_quota_check >= 10:
                with store.lock:
                    enforce_recording_quota(directory, settings['recording']['max_storage_mb'])
                last_quota_check = time.monotonic()
            if Path(settings['fisier_oprire']).is_file():
                stop_event.set()
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        print('Oprire controlata a serviciilor proprii...', flush=True)
        mqtt.close()
        consumer.close()
        telemetry.close()
        servicii.close()
        historian.close()
        if web_thread.is_alive():
            server.shutdown()
        server.server_close()
        if read_json(STATE_FILE).get('id') == instance_id:
            STATE_FILE.unlink(missing_ok=True)
        print('Aplicatia s-a oprit. Datele inregistrate raman disponibile.', flush=True)
        instance_lock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
