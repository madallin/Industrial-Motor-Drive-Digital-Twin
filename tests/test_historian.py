"""Exercise the real SQLite writer, cursor recovery, and bounded queries."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from application.config import load_config
from application.data_store import DataStore
from application.historian import Historian


class HistorianTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = load_config()
        self.settings['director_rezultate'] = self.directory.name
        self.store = DataStore(self.settings, 'test')
        self.stop = threading.Event()
        self.history = Historian(self.settings, self.store, self.stop)
        self.connection = self.history.connect_writer()
        self.addCleanup(self.connection.close)
        self.name = 'psim_test_part0001'
        self.path = Path(self.directory.name) / (self.name + '_samples.csv')
        self.path.write_text('t_s,rpm,rms_est_a,vdc_v,status\n' + ''.join(f'{i/1000},{i},1,565,RUNNING\n' for i in range(101)))
        self.events = self.path.with_name(self.name + '_events.csv')
        self.events.write_text('t_s,level,code,value\n0,STATE,DRIVE_STARTING,0\n0.02,ALARM,I_RMS_HIGH,13\n0.03,CLEARED,I_RMS_HIGH,8\n')

    def test_sampling_retains_events_and_restart_does_not_duplicate(self):
        self.history.poll(self.connection)
        result = self.history.query(self.name)
        self.assertEqual(result['sample_count'], 3)
        self.assertEqual(len(result['events']), 3)
        self.assertEqual(result['events'][1]['severity'], 'ALARM')
        self.assertEqual(result['samples'][0]['sim_time_s'], 0)
        self.assertGreater(result['samples'][0]['observed_epoch'], 1e9)
        self.assertEqual(self.history.sessions()[0]['source'], 'psim')
        again = Historian(self.settings, self.store, self.stop)
        again.poll(self.connection)
        self.assertEqual(again.query(self.name)['sample_count'], 3)
        self.assertEqual(len(again.query(self.name)['events']), 3)
        with self.path.open('a') as stream:
            stream.write('0.101,3,1,565,STOPPING\n0.102,4,1,565,STOPPING')
        again.poll(self.connection)
        self.assertEqual(again.query(self.name)['sample_count'], 4)
        with self.path.open('a') as stream:
            stream.write('\n0.16,5,1,565,STOPPING\n')
        again.poll(self.connection)
        self.assertEqual(again.query(self.name)['sample_count'], 5)

    def test_query_range_comparison_and_validation(self):
        self.history.poll(self.connection)
        other = self.path.with_name('psim_other_samples.csv')
        other.write_text('t_s,rpm,status\n0,200,READY\n1,400,RUNNING\n')
        self.history.poll(self.connection)
        result = self.history.query(self.name, 0.04, 0.11, limit=1)
        self.assertEqual(result['statistics']['rpm']['average'], 75)
        self.assertEqual(len(result['samples']), 1)
        self.assertIsNotNone(result['next_after'])
        self.assertEqual(self.history.query('psim_other')['statistics']['rpm']['average'], 300)
        for axis, start, end, limit in [('bad', 0, 1, 5), ('simulation', float('nan'), 1, 5), ('simulation', 2, 1, 5), ('simulation', 0, 1, 5000)]:
            with self.assertRaises(ValueError):
                self.history.query(self.name, start, end, axis, limit)
        self.assertEqual(self.history.query("'; DROP TABLE samples; --")['sample_count'], 0)

    def test_retention_prevents_reimport_and_failed_transaction_keeps_cursor(self):
        self.history.poll(self.connection)
        self.connection.execute('UPDATE samples SET observed_epoch=1')
        self.connection.commit()
        self.history.retain(self.connection)
        self.history.poll(self.connection)
        self.assertEqual(self.history.query(self.name)['sample_count'], 0)
        offset = self.connection.execute("SELECT offset FROM cursors WHERE kind='samples'").fetchone()[0]
        with self.path.open('a') as stream:
            stream.write('1,3,1,565,RUNNING\n')
        self.connection.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.Error):
            self.history.ingest(self.connection, self.store.sessions()[0])
        self.assertEqual(self.connection.execute("SELECT offset FROM cursors WHERE kind='samples'").fetchone()[0], offset)

    def test_disk_failure_is_isolated_and_can_recover(self):
        self.connection.close()
        # The worker retries without using the control service or blocking it.
        with patch.object(self.history, 'connect_writer', side_effect=sqlite3.OperationalError('disk full')):
            self.history.start()
            deadline = time.monotonic() + 2
            while self.history.state['error'] is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(self.history.state['available'])
            self.assertEqual(self.history.state['error'], 'OperationalError')
            self.stop.set()
            self.history.close()
        self.assertFalse(self.history.thread.is_alive())

    def test_service_events_have_separate_sources_and_bounded_ingestion(self):
        event = {'id': 'broker-loss', 'source': 'mqtt', 'origin': 'service', 'code': 'MQTT_DISCONNECTED',
                 'severity': 'WARN', 'level': 'WARN', 'observed_epoch': time.time()}
        self.history.enqueue_event(event)
        self.history.enqueue_event(event)
        self.history.poll(self.connection)
        events = self.history.query_events(source='mqtt')['events']
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]['sim_time_s'])
        self.assertEqual(self.history.query_events(source='psim')['events'][0]['source'], 'psim')
        for index in range(70):
            self.history.enqueue_event(dict(event, id=str(index)))
        self.assertEqual(self.history.service_events.qsize(), 64)
        self.assertEqual(self.history.state['dropped_service_events'], 6)


if __name__ == '__main__':
    unittest.main()
