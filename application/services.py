"""Manage owned processes without taking over existing Windows services."""
from collections import deque
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

from .config import PROJECT_ROOT, find_executable
from .data_store import write_json
from .windows_processes import ProcessGroup
from .control import HMIController


def check_broker(address, port):
    try:
        with socket.create_connection((address, port), timeout=0.5) as connection:
            connection.settimeout(0.5)
            # Probe MQTT 3.1.1 CONNECT with a short client ID and no credentials.
            connection.sendall(b'\x10\x11\x00\x04MQTT\x04\x02\x00\x05\x00\x05audit')
            response = connection.recv(4)
            connection.sendall(b'\xe0\x00')
            return 'MQTT' if len(response) == 4 and response[:2] == b'\x20\x02' else 'OCUPAT'
    except OSError:
        if address in ('127.0.0.1', 'localhost'):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
                    if os.name == 'nt':
                        check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    check.bind(('127.0.0.1', port))
                return 'LIBER'
            except OSError:
                pass
        return 'OCUPAT'


class ServiceManager:
    def __init__(self, settings, store, runtime_dir, stop_event):
        self.settings = settings
        self.store = store
        self.directory = runtime_dir
        self.stop_event = stop_event
        self.processes = {}
        self.event_log = deque(maxlen=40)
        self.messages = {}
        self.lock = threading.RLock()
        self.grup = ProcessGroup()
        self.octave = find_executable(settings['octave']['executabil'], 'octave-cli', ['GNU Octave/*/mingw64/bin/octave-cli.exe'])
        self.config_path = runtime_dir / 'configuratie_runtime.json'
        settings['director_control'] = str(runtime_dir)
        self.control = HMIController(settings, runtime_dir)
        write_json(self.config_path, settings)

    def launch(self, role, parser, environment=None, directory=None):
        process = subprocess.Popen(parser, cwd=directory or PROJECT_ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.grup.add(process)
        self.processes[role] = process
        threading.Thread(target=self.read_event_log, args=(role, process), daemon=True).start()
        self.messages[role] = 'Proces pornit.'
        return process

    def read_event_log(self, role, process):
        for line in iter(process.stdout.readline, b''):
            message = line.decode('utf-8', 'replace').strip()[:2000]
            if message:
                self.event_log.append({'serviciu': role, 'mesaj': message})
                print(f'[{role}] {message}', flush=True)
        process.stdout.close()

    def octave_environment(self):
        environment = os.environ.copy()
        environment['IDRIVE_CONFIG_RUNTIME'] = str(self.config_path)
        return environment

    def start(self):
        if self.settings['octave']['activ']:
            if self.octave:
                try:
                    self.launch('octave', [self.octave, '--quiet', '--no-gui', '--eval', 'run_psim_supervisor()'], self.octave_environment(), PROJECT_ROOT / 'octave')
                except OSError:
                    self.messages['octave'] = 'Executabilul GNU Octave nu a putut fi pornit.'
            else:
                self.messages['octave'] = 'GNU Octave nu este instalat sau calea configurata este invalida.'
        else:
            self.messages['octave'] = 'Receptia si calculele Octave sunt dezactivate.'
        mqtt = self.settings['mqtt']
        if mqtt['activ']:
            # TLS brokers are managed externally; don't probe them as plaintext
            # MQTT or replace their listener with an anonymous local broker.
            state = 'MQTT' if mqtt.get('tls') else check_broker(mqtt['adresa'], mqtt['port'])
            if state == 'MQTT':
                self.messages['broker'] = 'Broker existent; nu este detinut de orchestrator.'
            elif state == 'LIBER' and mqtt['porneste_broker_local'] and mqtt['adresa'] in ('127.0.0.1', 'localhost'):
                executable = find_executable(mqtt['executabil_broker'], 'mosquitto', ['Mosquitto/mosquitto.exe'])
                if executable:
                    file_path = self.directory / 'mosquitto.conf'
                    file_path.write_text(f'listener {mqtt["port"]} 127.0.0.1\nallow_anonymous true\npersistence false\nlog_dest stdout\n', encoding='ascii')
                    try:
                        self.launch('broker', [executable, '-c', str(file_path)])
                    except OSError:
                        self.messages['broker'] = 'Brokerul local nu poate fi pornit.'
                else:
                    self.messages['broker'] = 'Mosquitto lipseste; aplicatia functioneaza fara broker.'
            else:
                self.messages['broker'] = 'Broker indisponibil sau port ocupat; reconectare MQTT in fundal.'
        for role, message in self.messages.items():
            print(f'{role}: {message}', flush=True)

    def monitor(self):
        with self.lock:
            for role, process in self.processes.items():
                code = process.poll()
                if code is not None and self.messages.get(role) == 'Proces pornit.':
                    self.messages[role] = f'Proces terminat, cod {code}.'
                    print(f'{role}: {self.messages[role]}', flush=True)

    def state(self):
        with self.lock:
            return {role: {'activ': role in self.processes and self.processes[role].poll() is None, 'mesaj': message}
                    for role, message in self.messages.items()}

    def close(self):
        Path(self.settings['fisier_oprire']).touch()
        deadline = time.monotonic() + 6
        for role in ('octave',):
            process = self.processes.get(role)
            if process and process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    print(f'{role}: oprire fortata a procesului propriu dupa expirarea termenului.', flush=True)
                    process.terminate()
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        self.grup.close()
