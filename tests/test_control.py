"""Test the HMI command boundary, limits, ACK handling, and STOP priority."""
import copy
from pathlib import Path
import tempfile
import time
import unittest

from application.config import load_config
from application.control import HMIController
from application.data_store import write_json


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.settings = load_config()
        self.settings['orchestrator_id'] = 'verificare'
        self.settings['control']['psim_activ'] = True
        self.control = HMIController(self.settings, self.directory)
        self.applied = {'orchestrator_id': 'verificare', 'actualizat_epoch': time.time(),
                        'secventa': 0, 'mod': 'manual', 'pornit': True, 'frecventa_hz': 50, 'sarcina_nm': 5,
                        'conectat': True, 'protocol': 2, 'configured': True, 'drive_state': 'RUNNING', 'fault': 0,
                        'backend_activ': True, 'ack_epoch': time.time(), 'esantion_epoch': time.time(),
                        'canal_id': 'legatura'}
        self.write_feedback(self.applied)

    def tearDown(self):
        self.temporary.cleanup()

    def write_feedback(self, state, target='psim'):
        state = copy.deepcopy(state)
        state['actualizat_epoch'] = time.time()
        state['ack_epoch'] = time.time()
        state['esantion_epoch'] = time.time()
        write_json(self.directory / f'control_{target}_stare.json', state)

    def test_oprirea_inlocuieste_comanda_pending(self):
        _, code = self.control.submit({'tinta': 'psim', 'actiune': 'opreste'}, True)
        self.assertEqual(code, 202)
        request = self.control.requests['psim']
        self.assertFalse(request['pornit'])
        self.assertTrue(self.control.state(True)['psim']['in_asteptare'])
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste'}, True)[1], 409)
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'opreste'}, True)[1], 200)
        self.write_feedback(self.control.requests['psim'])
        self.assertFalse(self.control.state(True)['psim']['in_asteptare'])

    def test_frontiera_date_vechi_istoric_si_limite(self):
        self.assertEqual(self.control.submit({'tinta': 'istoric', 'actiune': 'porneste'}, True)[1], 400)
        self.assertEqual(self.control.submit({'tinta': 'model', 'actiune': 'porneste'}, True)[1], 400)
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'profil'}, True)[1], 400)
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste'}, False)[1], 503)
        self.applied['mod'] = 'manual'
        self.write_feedback(self.applied)
        for value in (float('nan'), float('inf'), -1, 51, True, '25'):
            self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'referinte',
                'frecventa_hz': value, 'sarcina_nm': 5}, True)[1], 400)
        self.applied['orchestrator_id'] = 'instanta_anterioara'
        self.write_feedback(self.applied)
        self.assertFalse(self.control.state(True)['psim']['disponibil'])

    def test_psim_cere_activare_explica_watchdog_si_secventa_creste(self):
        state = dict(self.applied, mod='manual', conectat=True, canal_id='legatura', secventa=30, pornit=False, drive_state='READY')
        self.write_feedback(state, 'psim')
        self.settings['control']['psim_activ'] = False
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste'}, True)[1], 503)
        self.settings['control']['psim_activ'] = True
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste'}, True)[1], 202)
        self.assertEqual(self.control.requests['psim']['canal_id'], 'legatura')
        self.assertGreater(self.control.requests['psim']['secventa'], 30)
        self.control.requests['psim']['expira_epoch'] = time.time() - 1
        self.assertTrue(self.control.state(True)['psim']['expirat'])

    def test_start_transmite_referintele_introduse_impreuna_cu_autorizarea(self):
        self.write_feedback(dict(self.applied, pornit=False, frecventa_hz=0, sarcina_nm=0, drive_state='READY'))
        message, code = self.control.submit({'tinta': 'psim', 'actiune': 'porneste'}, True)
        self.assertEqual(code, 400)
        self.assertIn('0 Hz', message['mesaj'])
        for frequency, load_nm in ((0, 3), (51, 3), (10, 11), (10, None)):
            self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste',
                'frecventa_hz': frequency, 'sarcina_nm': load_nm}, True)[1], 400)
        self.assertFalse((self.directory / 'control_psim_cerere.json').exists())
        self.assertEqual(self.control.submit({'tinta': 'psim', 'actiune': 'porneste',
            'frecventa_hz': 10, 'sarcina_nm': 3}, True)[1], 202)
        requested = self.control.requests['psim']
        self.assertEqual((requested['pornit'], requested['frecventa_hz'], requested['sarcina_nm']), (True, 10, 3))
        self.write_feedback(dict(self.applied, **requested))
        self.assertFalse(self.control.state(True)['psim']['in_asteptare'])

    def test_fara_pornire_automata_si_refuz_explicat(self):
        self.write_feedback(dict(self.applied, pornit=False, drive_state='PRECHARGE'))
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste_automat'}, True)[1],400)
        message, code = self.control.submit({'tinta':'psim','actiune':'porneste'}, True)
        self.assertEqual(code,409)
        self.assertIn('DC-link',message['mesaj'])
        self.assertFalse((self.directory / 'control_psim_cerere.json').exists())
        self.write_feedback(dict(self.applied, pornit=False, drive_state='READY', respingere={'secventa':1,'motiv':2}))
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste'}, True)[1],202)
        self.assertTrue(self.control.state(True)['psim']['respins'])

    def test_protection_and_stop_interlocks(self):
        self.write_feedback(dict(self.applied, drive_state='FAULT', fault=1, pornit=False))
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste'},True)[1],409)
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'reset'},True)[1],202)
        self.write_feedback(dict(self.applied, **self.control.requests['psim'], drive_state='STOPPING'))
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste'},True)[1],409)
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'opreste'},True)[1],200)

    def test_legacy_dll_cannot_control_or_bypass_ramp_limits(self):
        self.write_feedback(dict(self.applied, protocol=1))
        self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste'},True)[1],503)
        self.write_feedback(dict(self.applied, pornit=False, drive_state='READY'))
        for name, value in [('acceleration_s',0.1),('deceleration_s',1),('acceleration_s',float('inf'))]:
            self.assertEqual(self.control.submit({'tinta':'psim','actiune':'porneste',name:value},True)[1],400)


if __name__ == '__main__':
    unittest.main()
