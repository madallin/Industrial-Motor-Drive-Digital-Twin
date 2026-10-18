"""Local broker tests, including actual reconnect and re-subscription."""
from pathlib import Path
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from application.config import load_config, find_executable
from application.data_store import DataStore
from mqtt.consumer import MQTTConsumer
from mqtt.publisher import MQTTPublisher


def wait_until(condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for local integration state.')


class MQTTIntegrationTests(unittest.TestCase):
    def test_notifications_survive_broker_restart_without_duplicates(self):
        broker_path = find_executable('', 'mosquitto', ['Mosquitto/mosquitto.exe'])
        if not broker_path:
            self.skipTest('Mosquitto is not installed.')
        with tempfile.TemporaryDirectory() as temporary:
            with socket.socket() as port_socket:
                port_socket.bind(('127.0.0.1', 0))
                port = port_socket.getsockname()[1]
            settings = load_config()
            settings['mqtt'].update(adresa='127.0.0.1', port=port, tls=False)
            settings['director_rezultate'] = temporary
            config = Path(temporary) / 'mosquitto.conf'
            config.write_text(f'listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n')
            def start_broker():
                return subprocess.Popen([broker_path, '-c', str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            process = start_broker()
            stop = threading.Event()
            store = DataStore(settings, 'mqtt-test')
            publisher = MQTTPublisher(settings['mqtt'], store, stop)
            consumer = MQTTConsumer(settings, stop)
            try:
                consumer.start(); publisher.start()
                wait_until(lambda: consumer.status['connected'] and publisher.connected.is_set())
                event = {'schema': 'industrial-drive.event.v1', 'id': 'mqtt-test-event', 'source': 'psim',
                         'code': 'DRIVE_FAULT', 'severity': 'ALARM', 'observed_epoch': time.time()}
                publisher.publish('events', event, qos=1)
                publisher.publish('events', event, qos=1)
                wait_until(lambda: any(item['id'] == event['id'] for item in consumer.notifications.snapshot()))
                self.assertEqual(sum(item['id'] == event['id'] for item in consumer.notifications.snapshot()), 1)
                process.terminate(); process.wait(timeout=3)
                wait_until(lambda: not consumer.status['connected'] and not publisher.connected.is_set())
                process = start_broker()
                wait_until(lambda: consumer.status['connected'] and publisher.connected.is_set(), 15)
                event = dict(event, id='after-reconnect', observed_epoch=time.time())
                publisher.publish('events', event, qos=1)
                wait_until(lambda: any(item['id'] == 'after-reconnect' for item in consumer.notifications.snapshot()))
            finally:
                stop.set(); consumer.close(); publisher.close()
                process.terminate(); process.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
