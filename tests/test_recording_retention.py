from pathlib import Path
import tempfile
import unittest

from application.data_store import write_json
from application.recording_retention import enforce_recording_quota


class RecordingRetentionTests(unittest.TestCase):
    def test_quota_preserves_active_recent_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for part in range(1, 5):
                name = f'psim_session_part{part:04d}'
                (directory / f'{name}_samples.csv').write_bytes(b'0' * 2048)
                write_json(directory / f'{name}_meta.json',
                           {'schema': 'industrial-drive.sesiune.v2', 'achizitie': 'INREGISTRARE'})
            write_json(directory / 'stare_psim.json', {'segment_id': 'psim_session_part0001'})
            unrelated = directory / 'original_measurements.csv'
            unrelated.write_text('keep')
            enforce_recording_quota(directory, 0.006)
            self.assertTrue((directory / 'psim_session_part0001_samples.csv').exists())
            self.assertFalse((directory / 'psim_session_part0002_samples.csv').exists())
            self.assertTrue((directory / 'psim_session_part0003_samples.csv').exists())
            self.assertTrue((directory / 'psim_session_part0004_samples.csv').exists())
            self.assertTrue(unrelated.exists())
