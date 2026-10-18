"""Validate monitoring defaults and reject unsafe configuration values."""
from copy import deepcopy
import unittest

from application.config import load_config
from application.iiot_config import configure_iiot


class ConfigurationTests(unittest.TestCase):
    def test_missing_monitoring_settings_receive_valid_defaults(self):
        settings = load_config()
        del settings['iiot']
        configure_iiot(settings)
        self.assertEqual(set(settings['iiot']), {'historian', 'websocket', 'notifications'})
        self.assertEqual(settings['iiot']['historian']['sample_interval_s'], 0.05)
        self.assertTrue(settings['iiot']['websocket']['enabled'])

    def test_invalid_monitoring_settings_are_rejected(self):
        settings = load_config()
        for section, field, value in [
            ('historian', 'sample_interval_s', 0),
            ('historian', 'max_sample_rows', 200.5),
            ('websocket', 'max_clients', 1000),
            ('notifications', 'max_items', float('inf')),
        ]:
            with self.subTest(section=section, field=field):
                changed = deepcopy(settings)
                changed['iiot'][section][field] = value
                with self.assertRaises(ValueError):
                    configure_iiot(changed)

    def test_remote_broker_requires_tls(self):
        settings = load_config()
        settings['mqtt'].update(adresa='broker.example', tls=False)
        with self.assertRaises(ValueError):
            configure_iiot(settings)


if __name__ == '__main__':
    unittest.main()
