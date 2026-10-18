"""Validate monitoring and history settings without changing the drive-control contract."""
from copy import deepcopy
import math

DEFAULTS = {
    'historian': {'enabled': True, 'sample_interval_s': 0.05, 'retention_days': 30,
                  'max_sample_rows': 200000, 'max_event_rows': 50000, 'max_size_mb': 128},
    'websocket': {'enabled': True, 'interval_s': 0.75, 'max_clients': 8,
                  'event_buffer': 512, 'send_timeout_s': 3},
    'notifications': {'enabled': True, 'max_items': 200},
}


def finite_numeric(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


def configure_iiot(settings):
    supplied = settings.setdefault('iiot', {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
        raise ValueError('Configuratie IIoT invalida.')
    for section, defaults in DEFAULTS.items():
        values = supplied.setdefault(section, {})
        if not isinstance(values, dict) or set(values) - set(defaults):
            raise ValueError(f'Configuratie IIoT invalida: {section}.')
        for key, default in defaults.items():
            values.setdefault(key, deepcopy(default))
        if not isinstance(values['enabled'], bool):
            raise ValueError(f'IIoT {section}.enabled trebuie sa fie boolean.')
    bounds = {
        'historian': {'sample_interval_s': (0.01, 60), 'retention_days': (1, 3650),
                      'max_sample_rows': (100, 2000000), 'max_event_rows': (100, 500000), 'max_size_mb': (16, 1024)},
        'websocket': {'interval_s': (0.25, 5), 'max_clients': (1, 16),
                      'event_buffer': (64, 4096), 'send_timeout_s': (1, 10)},
        'notifications': {'max_items': (20, 1000)},
    }
    integers = {'retention_days', 'max_sample_rows', 'max_event_rows', 'max_size_mb',
                'max_clients', 'event_buffer', 'max_items'}
    for section, fields in bounds.items():
        for key, (low, high) in fields.items():
            value = supplied[section][key]
            if (not finite_numeric(value)
                    or not low <= value <= high or key in integers and not isinstance(value, int)):
                raise ValueError(f'Valoare IIoT invalida: {section}.{key}.')
    mqtt = settings['mqtt']
    mqtt.setdefault('tls', False)
    if not isinstance(mqtt['tls'], bool) or mqtt['adresa'] not in ('localhost', '127.0.0.1', '::1') and not mqtt['tls']:
        raise ValueError('Un broker MQTT la distanta necesita TLS.')
