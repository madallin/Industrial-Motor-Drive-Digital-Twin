"""Use real HTTP/WebSocket connections without a solver or motor commands."""
from pathlib import Path
import json
import socket
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.request import urlopen

from application.config import load_config
from application.data_store import DataStore
from application.historian import Historian
from application.telemetry import TelemetryHub
from dashboard.server import LocalServer, HMIRequestHandler
from mqtt.consumer import MQTTConsumer


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = load_config()
        settings['director_rezultate'] = self.temp.name
        self.stop = threading.Event()
        self.server = LocalServer(('127.0.0.1', 0), HMIRequestHandler)
        self.server.store = DataStore(settings, 'test')
        self.server.historian = Historian(settings, self.server.store, self.stop)
        self.server.servicii = SimpleNamespace(state=lambda: {}, control=SimpleNamespace(state=lambda active: {'psim': {'disponibil': False}}))
        self.server.mqtt = SimpleNamespace(state={'conectat': False})
        self.server.mqtt_consumer = MQTTConsumer(settings, self.stop)
        self.hub = self.server.telemetry = TelemetryHub(self.server, self.stop)
        self.hub.tick()
        self.hub.start()
        self.web = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.web.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.url = self.origin.replace('http:', 'ws:') + '/api/stream'
        self.addCleanup(self.close)

    def close(self):
        self.stop.set()
        self.hub.close()
        self.server.shutdown()
        self.server.server_close()
        self.web.join(timeout=2)

    def test_http_and_websocket_share_contract_and_reject_commands(self):
        from websockets.sync.client import connect
        from websockets.exceptions import ConnectionClosed
        with connect(self.url, origin=self.origin, proxy=None) as client:
            frame = json.loads(client.recv(timeout=3))
            self.assertEqual(frame['schema'], 'industrial-drive.stream.v1')
            self.assertIsNone(frame['system']['psim']['ultim'])
            self.assertFalse(frame['system']['control']['psim']['disponibil'])
            with urlopen(self.origin + '/api/stare') as response:
                http = json.load(response)
            self.assertEqual(set(frame['system']), set(http))
            client.send('{"actiune":"porneste"}')
            with self.assertRaises(ConnectionClosed) as closed:
                while True:
                    client.recv(timeout=3)
            self.assertEqual(closed.exception.rcvd.code, 1008)
        with self.assertRaises(Exception):
            connect(self.url, origin='https://untrusted.invalid', proxy=None)

    def test_event_order_overrun_and_latest_telemetry_policy(self):
        for index in range(600):
            self.hub.add_event({'id': str(index), 'source': 'test', 'observed_epoch': time.time(), 'code': 'TEST', 'severity': 'INFO'})
        events, gap = self.hub.since(1)
        self.assertTrue(gap)
        self.assertEqual([e['sequence'] for e in events], sorted(e['sequence'] for e in events))
        frame = self.hub.frame(1, -10, 30)
        self.assertTrue(frame['event_gap'])
        self.assertGreater(frame['telemetry_skipped'], 0)
        self.assertEqual(len(self.hub.events), self.hub.settings['event_buffer'])
        self.hub.add_event({'id': '599', 'code': 'DUPLICATE'})
        self.assertEqual(len(self.hub.events), self.hub.settings['event_buffer'])

    def test_blocked_writer_deadline_closes_only_slow_client(self):
        class SlowSocket:
            closed = False
            def shutdown(self, how):
                self.closed = True
        slow, healthy = SlowSocket(), SlowSocket()
        with self.hub.lock:
            self.hub.clients[slow] = time.monotonic() - 10
            self.hub.clients[healthy] = 0
        self.hub.tick()
        self.assertTrue(slow.closed)
        self.assertFalse(healthy.closed)
        self.assertIsNotNone(self.hub.latest)

    def test_fast_simulation_does_not_skip_intervening_csv_segments(self):
        from application.data_store import write_json
        self.stop.set(); self.hub.thread.join(timeout=2)
        root = Path(self.temp.name)
        for part in range(1, 4):
            name = f'psim_fast_part{part:04d}'
            (root / (name + '_samples.csv')).write_text(f't_s,rpm,status\n{part},100,RUNNING\n')
            (root / (name + '_events.csv')).write_text(f't_s,level,code,value\n{part},STATE,DRIVE_RUNNING,{part}\n')
            write_json(root / (name + '_meta.json'), {'orchestrator_id': 'test', 'session_id': 'psim_fast'})
        write_json(root/'stare_psim.json', {'sursa': 'psim', 'schema': 'industrial-drive.sesiune.v2', 'orchestrator_id': 'test',
            'actualizat_epoch': time.time(), 'esantion_epoch': time.time(), 'achizitie': 'ACTIV',
            'session_id': 'psim_fast', 'segment_id': 'psim_fast_part0003'})
        self.hub.tick()
        events, _ = self.hub.since(0)
        self.assertEqual([event['sim_time_s'] for event in events if event['code'] == 'DRIVE_RUNNING'], [1, 2, 3])
        self.hub.tick()
        events, _ = self.hub.since(0)
        self.assertEqual(sum(event['code'] == 'DRIVE_RUNNING' for event in events), 3)

        # Entire completed runs must still publish their recorded events when
        # the supervisor has already returned to an idle snapshot.
        self.hub.offsets.clear(); self.hub.events.clear(); self.hub.seen.clear()
        write_json(root/'stare_psim.json', {'sursa': 'psim', 'orchestrator_id': 'test', 'actualizat_epoch': time.time(), 'achizitie': 'ASTEPTARE'})
        self.hub.tick()
        events, _ = self.hub.since(0)
        self.assertEqual(sum(event['code'] == 'DRIVE_RUNNING' for event in events), 3)

    def test_large_event_backlog_preserves_segment_order(self):
        from application.data_store import write_json
        self.stop.set(); self.hub.thread.join(timeout=2)
        root = Path(self.temp.name)
        for part in (1, 2):
            name = f'psim_backlog_part{part:04d}'
            (root / (name + '_samples.csv')).write_text('t_s,rpm,status\n0,0,READY\n')
            write_json(root/(name + '_meta.json'), {'orchestrator_id': 'test'})
        code = 'EVENT_' + 'A'*100
        (root/'psim_backlog_part0001_events.csv').write_text('t_s,level,code,value\n' + ''.join(f'{index},INFO,{code},{index}\n' for index in range(3000)))
        (root/'psim_backlog_part0002_events.csv').write_text('t_s,level,code,value\n3001,INFO,LATER_SEGMENT,1\n')
        self.hub.tick()
        self.assertFalse(any(event['code'] == 'LATER_SEGMENT' for event in self.hub.events))
        self.hub.tick()
        self.assertEqual(self.hub.events[-1]['code'], 'LATER_SEGMENT')



class NotificationTests(unittest.TestCase):
    def test_invalid_duplicate_and_acknowledgement_do_not_reset_alarm(self):
        from mqtt.consumer import Notifications
        notifications = Notifications(20)
        event = {'schema': 'industrial-drive.event.v1', 'id': 'alarm-1', 'source': 'psim',
                 'code': 'DRIVE_FAULT', 'severity': 'ALARM', 'observed_epoch': time.time()}
        self.assertTrue(notifications.add(event))
        self.assertFalse(notifications.add(event))
        self.assertTrue(notifications.acknowledge('alarm-1'))
        self.assertEqual(notifications.snapshot()[0]['severity'], 'ALARM')
        self.assertIsNotNone(notifications.snapshot()[0]['acknowledged_epoch'])
        self.assertFalse(notifications.acknowledge('unknown'))
        for changed in ({'observed_epoch': 1}, {'observed_epoch': float('nan')}, {'observed_epoch': 10**500}, {'severity': 'RESET'}, {'id': []}, {'value': float('inf')}, {'sim_time_s': []}):
            with self.assertRaises(ValueError):
                notifications.add(dict(event, **changed))

    def test_reconnect_resubscribes_and_unavailable_broker_is_nonfatal(self):
        settings = load_config()
        consumer = MQTTConsumer(settings, threading.Event())
        calls = []
        client = SimpleNamespace(subscribe=lambda subscriptions: (calls.append(subscriptions) or (0, 1)))
        reason = SimpleNamespace(is_failure=False)
        consumer.on_connect(client, None, None, reason, None)
        consumer.on_disconnect(client, None, None, 1, None)
        consumer.on_connect(client, None, None, reason, None)
        self.assertEqual(calls[0], calls[1])
        self.assertTrue(consumer.status['connected'])
        message = SimpleNamespace(topic=settings['mqtt']['prefix'] + '/events', payload=b'{"x":NaN}', retain=False)
        consumer.on_message(None, None, message)
        self.assertEqual(consumer.status['rejected_messages'], 1)


if __name__ == '__main__':
    unittest.main()
