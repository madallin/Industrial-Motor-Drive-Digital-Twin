"""Load and validate configuration at the external process boundary."""
import json
import math
from pathlib import Path
import shutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def bounded_number(value, minimum, maximum, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Parametru invalid: {name} ({minimum}..{maximum}).')


def load_config(file_path=None):
    file_path = Path(file_path or PROJECT_ROOT / 'config/app_config.json').resolve()
    settings = json.loads(file_path.read_text(encoding='utf-8-sig'))
    for value in (settings['deschide_browser'], settings['octave']['activ'], settings['psim']['receptie_activa'], settings['mqtt']['activ'], settings['mqtt']['porneste_broker_local']):
        if not isinstance(value, bool):
            raise ValueError('Optiunile de activare trebuie sa fie true sau false.')
    for name in ('port_web',):
        bounded_number(settings[name], 1024, 65535, name)
        if not isinstance(settings[name], int):
            raise ValueError('Portul trebuie sa fie intreg.')
    for grup, name in (('mqtt', 'port'), ('psim', 'port_tcp')):
        bounded_number(settings[grup][name], 1024, 65535, name)
        if not isinstance(settings[grup][name], int):
            raise ValueError('Portul trebuie sa fie intreg.')
    for name, minimum, maximum in [('fereastra_s', 0.1, 86400), ('puncte_maxime', 100, 2500), ('date_vechi_s', 1, 120), ('retentie_zile', 0, 3650)]:
        bounded_number(settings[name], minimum, maximum, name)
    if not isinstance(settings['puncte_maxime'], int):
        raise ValueError('Numarul de puncte trebuie sa fie intreg.')
    bounded_number(settings['psim']['segment_s'], 5, 3600, 'psim.segment_s')
    control = settings.setdefault('control', {'frecventa_max_hz': 50, 'sarcina_max_nm': 10,
                                                  'expirare_comanda_s': 5, 'psim_activ': False})
    for name, minimum, maximum in [('frecventa_max_hz', 1, 1000), ('sarcina_max_nm', 0.001, 10000), ('expirare_comanda_s', 1, 30)]:
        bounded_number(control[name], minimum, maximum, name)
    if not isinstance(control['psim_activ'], bool):
        raise ValueError('control.psim_activ trebuie sa fie true sau false.')
    for name, default, low, high in [('acceleration_s', 2, 1, 30), ('deceleration_s', 5, 2, 60),
                                    ('watchdog_s', 2, 1, 10), ('backend_lease_s', 2, 1, 10)]:
        bounded_number(control.setdefault(name, default), low, high, name)
    protection = settings['protection']
    for name in ('rated_current_a', 'trip_current_a', 'dc_low_v', 'dc_high_v',
                 'max_speed_rpm', 'ready_low_v', 'ready_high_v'):
        bounded_number(protection[name], 0.001, 10000, name)
    if not (protection['rated_current_a'] <= protection['trip_current_a'] <= 2*protection['rated_current_a']
            and protection['dc_low_v'] < protection['ready_low_v'] < protection['ready_high_v'] < protection['dc_high_v'] <= 1000
            and protection['rated_current_a'] <= 100):
        raise ValueError('Praguri de protectie incoerente.')
    if control['frecventa_max_hz'] > 50 or control['sarcina_max_nm'] > 10:
        raise ValueError('Limitele acestui circuit sunt 50 Hz si 10 Nm.')
    bounded_number(settings['recording']['max_storage_mb'], 16, 8192, 'max_storage_mb')
    for name, value in settings['diagnostic'].items():
        bounded_number(value, 0, 1e6, name)
    diagnostic = settings['diagnostic']
    obligatorii = ('ready_vdc_low_v ready_vdc_high_v ready_hold_s ready_span_max_v ready_min_count stop_vdc_max_v sample_window_s sample_min_count warn_hold_s clear_hold_s current_enable_after_s current_warn_a current_alarm_a current_clear_warn_a current_clear_alarm_a vdc_enable_after_s vdc_warn_low_v vdc_alarm_low_v vdc_warn_high_v vdc_alarm_high_v vdc_warn_low_clear_v vdc_alarm_low_clear_v vdc_warn_high_clear_v vdc_alarm_high_clear_v motor_pole_pairs speed_enable_f_hz speed_settle_s speed_warn_pct speed_alarm_pct speed_warn_clear_pct speed_alarm_clear_pct').split()
    if set(diagnostic) != set(obligatorii):
        raise ValueError('Configuratia diagnosticului este incompleta sau contine chei necunoscute.')
    if not diagnostic['current_clear_warn_a'] < diagnostic['current_warn_a'] < diagnostic['current_alarm_a'] or not diagnostic['current_clear_alarm_a'] < diagnostic['current_alarm_a']:
        raise ValueError('Pragurile RMS sau histerezisul sunt incoerente.')
    if not diagnostic['vdc_alarm_low_v'] < diagnostic['vdc_warn_low_v'] < diagnostic['vdc_warn_high_v'] < diagnostic['vdc_alarm_high_v']:
        raise ValueError('Pragurile DC-link sunt incoerente.')
    if not diagnostic['speed_warn_clear_pct'] < diagnostic['speed_warn_pct'] < diagnostic['speed_alarm_pct'] or not diagnostic['speed_alarm_clear_pct'] < diagnostic['speed_alarm_pct']:
        raise ValueError('Pragurile abaterii de turatie sunt incoerente.')
    if int(diagnostic['motor_pole_pairs']) != diagnostic['motor_pole_pairs']:
        raise ValueError('Numarul perechilor de poli trebuie sa fie intreg.')
    for name in ('sample_window_s', 'warn_hold_s', 'clear_hold_s', 'motor_pole_pairs'):
        if diagnostic[name] <= 0:
            raise ValueError(f'Parametru pozitiv necesar: {name}.')
    mqtt = settings['mqtt']
    if not isinstance(mqtt['adresa'], str) or not mqtt['adresa'] or any(ord(character) < 32 for character in mqtt['adresa']):
        raise ValueError('Adresa MQTT invalida.')
    if not isinstance(mqtt['prefix'], str) or not mqtt['prefix'].strip('/') or any(character in mqtt['prefix'] for character in '+#\x00'):
        raise ValueError('Prefix MQTT invalid.')
    directory = Path(settings['director_rezultate'])
    directory = (PROJECT_ROOT / directory).resolve() if not directory.is_absolute() else directory.resolve()
    if not directory.is_relative_to(PROJECT_ROOT) or directory == PROJECT_ROOT:
        raise ValueError('Rezultatele trebuie pastrate intr-un subdirector al proiectului.')
    settings['director_rezultate'] = str(directory)
    return settings


def find_executable(configured, name, candidates):
    if configured:
        file_path = Path(configured).expanduser()
        return str(file_path.resolve()) if file_path.is_file() else shutil.which(configured)
    available = shutil.which(name)
    if available:
        return available
    for candidate in candidates:
        matches = sorted(Path('C:/Program Files').glob(candidate), reverse=True)
        if matches:
            return str(matches[0])
    return None
