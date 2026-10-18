"""Exercise Octave transport and the x86 DLL in an isolated host."""
from collections import deque
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from application.config import PROJECT_ROOT
from tests.test_system_integration import wait_for, free_port


def compile_test(directory, port):
    compiler = Path('C:/msys64/mingw32/bin/gcc.exe')
    environment = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ['PATH'])
    dll = directory / 'psim_hmi_test.dll'
    host = directory / 'harness_hmi.exe'
    subprocess.run([str(compiler), '-shared', '-O2', '-Wall', '-Wextra', '-Werror', '-static-libgcc',
        '-Wl,--kill-at', f'-DPORT_HMI={port}', '-o', str(dll), str(PROJECT_ROOT/'bridge/psim_hmi.c'), '-lws2_32'], check=True, env=environment)
    subprocess.run([str(compiler), '-O2', '-Wall', '-Wextra', '-Werror', '-static-libgcc',
        '-o', str(host), str(PROJECT_ROOT/'tests/harness_hmi.c')], check=True, env=environment)
    return dll, host


def start_host(dll, host):
    process = subprocess.Popen([str(host), str(dll)], stdout=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)
    traces = deque(maxlen=2000)
    def read():
        for row in process.stdout:
            traces.append([float(value) for value in row.decode().strip().split(',')])
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return process, traces, thread


def verify_dll(directory):
    port = free_port()
    dll, host = compile_test(directory, port)
    with socket.socket() as server:
        server.bind(('127.0.0.1', port)); server.listen(); server.settimeout(5)
        process, traces, thread = start_host(dll, host)
        try:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                file = connection.makefile('rb')
                def ack(condition):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        row = file.readline().decode().strip().split(',')
                        if row[0] == 'ACK':
                            values = [float(value) for value in row[1:]]
                            if condition(values): return values
                    raise AssertionError('DLL-ul nu a confirmat starea asteptata.')
                def nack(sequence, reason):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        row = file.readline().decode().strip().split(',')
                        if row[0] == 'NACK' and row[1:] == [str(sequence), str(reason)]:
                            return
                    raise AssertionError('DLL-ul nu a explicat refuzul comenzii.')
                assert file.readline() == b'HELLO,HMI,2\n'
                ack(lambda values: values[0] == 0 and values[1] == 0)
                connection.sendall(b'CFG,50,10,8.2,12.3,470,650,1650,510,610,2\n')
                ack(lambda values: values[12] == 1)
                ack(lambda values: values[6] == 1)
                connection.sendall(b'CMD,1,1,51,5,2,5,0\n')
                nack(1,1)
                connection.sendall(b'CMD,1,1,25')
                time.sleep(0.05)
                assert traces[-1][2] == 0, 'Comanda partiala nu trebuie aplicata.'
                connection.sendall(b',5,2,5,0\n')
                ack(lambda values: values[:4] == [1,1,25,5])
                heartbeat_stop = threading.Event()
                def heartbeat():
                    while not heartbeat_stop.wait(0.2):
                        connection.sendall(b'CMD,1,1,25,5,2,5,0\n')
                heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
                heartbeat_thread.start()
                try:
                    wait_for(lambda: traces[-1][1:4] == [25,1,5])
                finally:
                    heartbeat_stop.set(); heartbeat_thread.join(timeout=1)
                connection.sendall(b'CMD,2,1,nan,5,2,5,0\nCMD,0,1,50,5,2,5,0\nCMD,2,1,20,5,2,5,0,extra\n')
                ack(lambda values: values[:4] == [1,1,25,5])
                connection.sendall(b'CMD,2,1,30,4,2,5,0\n')
                ack(lambda values: values[:4] == [2,1,30,4])
                ack(lambda values: values[0] == 2 and values[1] == 0 and values[4] == 1)
                wait_for(lambda: traces[-1][1:3] == [0,0])
                connection.sendall(b'CMD,2,1,30,4,2,5,0\n')
                ack(lambda values: values[0] == 2 and values[1] == 0 and values[4] == 1)
                assert traces[-1][2] == 0, 'Heartbeat-ul vechi nu trebuie sa reporneasca.'
                # RESET requires 100 ms of stationary feedback after the trip.
                # A zero PWM output alone doesn't establish that qualification.
                stopped_at = traces[-1][0]
                wait_for(lambda: traces[-1][0] >= stopped_at + 0.2)
                connection.sendall(b'CMD,3,0,15,2,2,5,1\n')
                ack(lambda values: values[0] == 3 and values[7] == 0)
                ack(lambda values: values[6] == 5)
                connection.sendall(b'CMD,4,1,15,2,2,5,0\n')
                ack(lambda values: values[:4] == [4,1,15,2] and values[4] == 0)
                file.close()
            connection, _ = server.accept()
            with connection:
                file = connection.makefile('rb')
                assert file.readline() == b'HELLO,HMI,2\n'
                assert file.readline().decode().startswith('ACK,0,0,0,0,0,2')
                file.close()
            print('DLL x86: fragmentare, limite, ACK, watchdog, rearmare explicita si reconectare verificate.')
        finally:
            process.terminate(); process.wait(timeout=3); thread.join(timeout=1); process.stdout.close()


def verify_motor(directory):
    settings = json.loads((PROJECT_ROOT/'config/app_config.json').read_text())
    settings['port_web'] = free_port()
    settings['psim']['port_tcp'] = free_port()
    settings['mqtt']['activ'] = False
    settings['control']['psim_activ'] = True
    settings['control']['deceleration_s'] = 2
    settings['director_rezultate'] = str(directory/'date')
    settings['deschide_browser'] = False
    file_path = directory/'configuratie.json'
    file_path.write_text(json.dumps(settings))
    dll, host_executable = compile_test(directory, settings['psim']['port_tcp'])
    event_log = (directory/'jurnal.log').open('wb')
    process = subprocess.Popen([sys.executable, str(PROJECT_ROOT/'orchestrator.py'), '--config', str(file_path), '--fara-browser'],
        cwd=PROJECT_ROOT, stdout=event_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    host_process = None
    base_url = f'http://127.0.0.1:{settings["port_web"]}'
    def system():
        return json.load(urllib.request.urlopen(base_url+'/api/stare', timeout=3))
    def command(target, action, **references):
        request = urllib.request.Request(base_url+'/api/control', data=json.dumps(dict(tinta=target,actiune=action,**references)).encode(),
            headers={'Content-Type':'application/json','Origin':base_url})
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 202
            sequence = json.load(response)['secventa']
        return wait_for(lambda: (data if (data:=system())['control'][target]['aplicat']['secventa'] == sequence else None))
    try:
        wait_for(lambda: system()['receptie']['actual'])
        assert 'model' not in system()
        assert system()['control']['psim']['disponibil'] is False
        host_process, traces, thread = start_host(dll,host_executable)
        wait_for(lambda: system()['control']['psim']['disponibil'])
        assert system()['control']['psim']['aplicat']['ack_epoch'] > 0
        wait_for(lambda: system()['control']['psim']['aplicat']['drive_state'] == 'READY')
        try:
            command('psim', 'porneste', frecventa_hz=0, sarcina_nm=0)
            raise AssertionError('START la 0 Hz trebuie refuzat.')
        except urllib.error.HTTPError as error:
            assert error.code == 400
        assert traces[-1][1:3] == [0, 0]
        assert system()['control']['psim']['aplicat']['pornit'] is False
        data = command('psim', 'porneste', frecventa_hz=50, sarcina_nm=5)
        wait_for(lambda: traces[-1][1:4] == [50, 1, 5])
        command('psim', 'opreste')
        wait_for(lambda: traces[-1][1:3] == [0, 0])
        assert traces[-1][1:3] == [0, 0], 'STOP nu trebuie sa produca repornire.'
        wait_for(lambda: system()['control']['psim']['aplicat']['drive_state'] == 'STOPPED')
        command('psim','referinte',frecventa_hz=25,sarcina_nm=3)
        data = command('psim','porneste', frecventa_hz=10, sarcina_nm=2)
        assert data['control']['psim']['aplicat']['pornit'] is True
        assert data['control']['psim']['aplicat']['frecventa_hz'] == 10
        assert data['control']['psim']['aplicat']['sarcina_nm'] == 2
        wait_for(lambda: traces[-1][1:4] == [10,1,2])
        wait_for(lambda: system()['psim']['ultim']['frecventa'] == 10)
        command('psim','opreste')
        wait_for(lambda: traces[-1][1:3] == [0,0])
        assert system()['receptie']['dll_hmi'] and system()['receptie']['cadre_valide'] > 0
        assert not list((directory/'date').glob('model_*'))
        print('HMI -> Python -> Octave -> DLL: referinte, pornire, oprire, ACK si telemetrie verificate. Gazda DLL de test, fara circuit PSIM.')
    finally:
        if host_process:
            host_process.terminate(); host_process.wait(timeout=3); thread.join(timeout=1); host_process.stdout.close()
        runtime = json.loads((PROJECT_ROOT/'.runtime.json').read_text())
        if Path(runtime['fisier_oprire']).is_relative_to(directory):
            Path(runtime['fisier_oprire']).touch()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate(); process.wait(timeout=3)
        event_log.close()
        if process.returncode:
            print((directory/'jurnal.log').read_text(errors='replace'))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='control_',dir=PROJECT_ROOT/'results') as temporary:
        directory = Path(temporary)
        verify_dll(directory)
        verify_motor(directory)
