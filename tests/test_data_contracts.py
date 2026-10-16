"""Verify persistence, data provenance, and export contracts."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from application.config import load_config
from application.data_store import CsvReader, DataStore, aggregate_points, write_json, parse_sample


class DataContractTests(unittest.TestCase):
    def test_calcul_octave_existent_expune_abaterea_fara_valoare_inventata(self):
        result = parse_sample({'t_s': '1', 'sync_rpm': '1500', 'speed_error_pct': '4.6'})
        self.assertEqual(result['abatere_pct'], 4.6)
        self.assertIsNone(result['abatere'])
        self.assertIsNone(parse_sample({'t_s': '1'})['abatere_pct'])

    def test_rand_incomplet_si_memorie_limitata(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / 'date.csv'
            file_path.write_bytes(b't_s,rpm\n0,1\n1,2')
            reader = CsvReader(file_path, limit=3)
            self.assertEqual(len(reader.actualizeaza()), 1)
            with file_path.open('ab') as file:
                file.write(b'\n2,3\n3,4\n4,5\n')
            self.assertEqual(len(reader.actualizeaza()), 4)
            self.assertEqual(len(reader.rows), 3)
            self.assertEqual(reader.rows[-1]['rpm'], '5')
            self.assertEqual(reader.actualizeaza(), [])

    def test_agregare_pastreaza_varf_si_capete(self):
        points = [{'t': index, 'rpm': 100000 if index == 5001 else 0} for index in range(20000)]
        agregate = aggregate_points(points, 1000)
        self.assertLessEqual(len(agregate), 1000)
        self.assertEqual(agregate[0]['t'], 0)
        self.assertEqual(agregate[-1]['t'], 19999)
        self.assertTrue(any(point['rpm'] == 100000 for point in agregate))

    def test_istoric_nu_devine_live_si_cale_validata(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_config()
            settings['director_rezultate'] = directory
            file_path = Path(directory)
            name = 'drive_test'
            (file_path / f'{name}_samples.csv').write_text('t_s,rpm,status\n0,10,RUNNING\n', encoding='utf-8')
            (file_path / f'{name}_events.csv').write_text('t_s,level,code,value\n0,ALARM,I_RMS_HIGH,9\n1,CLEARED,I_RMS_HIGH,4\n', encoding='utf-8')
            store = DataStore(settings, 'instanta')
            data = store.recording(name)
            self.assertEqual(data['achizitie'], 'INREGISTRARE')
            self.assertEqual(data['alarme'], [])
            self.assertEqual(data['istoric_alarme'][0]['revenire_s'], 1)
            self.assertIsNone(store.session_path('../README'))
            write_json(file_path / 'stare_psim.json', {'sursa':'psim', 'orchestrator_id':'alta_instanta', 'actualizat_epoch':time.time(), 'esantion_epoch':time.time(), 'segment_id':name, 'achizitie':'ACTIV'})
            self.assertEqual(store.live_source('psim')['achizitie'], 'INDISPONIBIL')
            write_json(file_path / 'stare_psim.json', {'sursa':'psim', 'orchestrator_id':'instanta', 'actualizat_epoch':time.time(), 'esantion_epoch':time.time()-100, 'segment_id':name, 'achizitie':'ACTIV'})
            self.assertEqual(store.live_source('psim')['achizitie'], 'ASTEPTARE')
            self.assertIsNone(store.live_source('psim')['ultim'])


if __name__ == '__main__':
    unittest.main()
