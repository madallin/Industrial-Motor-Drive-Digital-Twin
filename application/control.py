"""Issue local drive commands and distinguish HTTP acceptance from controller ACK."""
import threading
import time

from .config import bounded_number
from .data_store import read_json, write_json


class HMIController:
    def __init__(self, settings, directory):
        self.settings = settings
        self.directory = directory
        self.lock = threading.RLock()
        self.sequence = 0
        self.requests = {}

    def state(self, motor_active):
        with self.lock:
            result = {'limite': self.settings['control']}
            for target in ('psim',):
                applied = read_json(self.directory / f'control_{target}_stare.json')
                now = time.time()
                fresh = (applied.get('orchestrator_id') == self.settings['orchestrator_id']
                            and 0 <= now - applied.get('actualizat_epoch', 0) < 2.5)
                current_ack = fresh and 0 <= now - applied.get('ack_epoch', 0) < 2.5
                current_feedback = fresh and 0 <= now - applied.get('esantion_epoch', 0) < 3
                available = motor_active and fresh and current_ack and current_feedback
                reason = ''
                if target == 'psim':
                    available = available and applied.get('backend_activ', False) and applied.get('conectat', False) and applied.get('protocol') == 2 and applied.get('configured', False) and self.settings['control']['psim_activ']
                    if not self.settings['control']['psim_activ']:
                        reason = 'Pregatit pentru DLL HMI; activati numai dupa conectarea iesirilor in schema PSIM.'
                    elif not motor_active or not fresh:
                        reason = 'Control indisponibil: GNU Octave nu raspunde.'
                    elif not applied.get('backend_activ', False):
                        reason = 'Control indisponibil: legatura cu backendul este intrerupta.'
                    elif not applied.get('conectat', False) or not current_ack:
                        reason = 'Control indisponibil: legatura cu DLL/PSIM este intrerupta.'
                    elif applied.get('protocol') != 2 or not applied.get('configured', False):
                        reason = 'Control indisponibil: configuratia DLL nu este confirmata.'
                    elif not current_feedback:
                        reason = 'Control indisponibil: masuratorile PSIM sunt vechi.'
                requested = self.requests.get(target)
                if requested and requested.get('canal_id') != applied.get('canal_id'):
                    requested = None
                confirmed = bool(requested and fresh and applied.get('secventa') == requested['secventa'])
                rejection = applied.get('respingere')
                rejected = bool(requested and isinstance(rejection, dict) and rejection.get('secventa') == requested['secventa'])
                expired = bool(requested and not confirmed and not rejected and now > requested['expira_epoch'])
                result[target] = {'disponibil': bool(available), 'motiv': reason,
                    'aplicat': applied if fresh else None, 'cerut': requested,
                    'in_asteptare': bool(requested and not confirmed and not rejected and not expired),
                    'confirmat': confirmed, 'respins': rejected,
                    'motiv_respingere': rejection.get('motiv') if rejected else None,
                    'expirat': expired}
            return result

    def submit(self, request, motor_active):
        if not isinstance(request, dict) or set(request) - {'tinta', 'actiune', 'frecventa_hz', 'sarcina_nm', 'acceleration_s', 'deceleration_s'}:
            return {'mesaj': 'Comanda invalida.'}, 400
        target, action = request.get('tinta'), request.get('actiune')
        if target != 'psim' or action not in ('porneste', 'opreste', 'referinte', 'reset'):
            return {'mesaj': 'Tinta sau actiune invalida.'}, 400
        with self.lock:
            context = self.state(motor_active)[target]
            if not context['disponibil']:
                return {'mesaj': context['motiv']}, 503
            previous = context['aplicat']
            if context['in_asteptare'] and action != 'opreste':
                return {'mesaj': 'Asteptati confirmarea comenzii precedente.'}, 409
            if action == 'opreste' and context['in_asteptare'] and not context['cerut']['pornit']:
                return {'mesaj': 'Oprirea este deja solicitata.'}, 200
            if action in ('porneste', 'referinte') and previous.get('fault'):
                return {'mesaj': 'Resetati protectia dupa eliminarea cauzei.'}, 409
            if action == 'porneste':
                if previous.get('pornit'):
                    return {'mesaj': 'Pornirea este deja solicitata; folositi Aplicare referinte pentru modificari.'}, 200
                if previous.get('drive_state') in ('STOPPING', 'COASTING'):
                    return {'mesaj': 'Pornire blocata: motorul este in curs de oprire.'}, 409
                if previous.get('drive_state') == 'PRECHARGE':
                    return {'mesaj': 'Pornire blocata: DC-link nepregatit.'}, 409
                if previous.get('drive_state') not in ('READY', 'STOPPED'):
                    return {'mesaj': 'Pornire blocata: starea actionarii nu permite START.'}, 409
            if action == 'opreste' and not context['in_asteptare'] and not previous.get('pornit'):
                return {'mesaj': 'Oprirea este deja solicitata.'}, 200
            if action == 'reset' and not previous.get('fault'):
                return {'mesaj': 'Nu exista un defect memorat.'}, 200
            if action == 'referinte' and previous.get('drive_state') in ('STOPPING', 'COASTING'):
                return {'mesaj': 'Asteptati finalizarea opririi.'}, 409
            command = {key: previous[key] for key in ('mod', 'pornit', 'frecventa_hz', 'sarcina_nm')}
            command.update(acceleration_s=previous.get('acceleration_s', self.settings['control']['acceleration_s']),
                           deceleration_s=previous.get('deceleration_s', self.settings['control']['deceleration_s']), reset=action == 'reset')
            if action in ('porneste', 'opreste', 'reset'):
                command['pornit'] = action == 'porneste'
            if action == 'referinte' or (action == 'porneste' and
                    any(key in request for key in ('frecventa_hz', 'sarcina_nm'))):
                if command['mod'] != 'manual':
                    return {'mesaj': 'Starea DLL nu confirma modul manual.'}, 409
                limits = self.settings['control']
                try:
                    for key, maximum in [('frecventa_hz', limits['frecventa_max_hz']), ('sarcina_nm', limits['sarcina_max_nm'])]:
                        bounded_number(request.get(key), 0, maximum, key)
                        command[key] = request[key]
                except ValueError as error:
                    return {'mesaj': str(error)}, 400
            try:
                for name, low, high in [('acceleration_s', 1, 30), ('deceleration_s', 2, 60)]:
                    value = request.get(name, command[name])
                    bounded_number(value, low, high, name)
                    command[name] = value
            except ValueError as error:
                return {'mesaj': str(error)}, 400
            if action == 'porneste' and command['frecventa_hz'] <= 0:
                return {'mesaj': 'Introduceti o frecventa mai mare de 0 Hz pentru START.'}, 400
            self.sequence = max(self.sequence, previous['secventa']) + 1
            command.update(secventa=self.sequence, orchestrator_id=self.settings['orchestrator_id'],
                           emis_epoch=time.time(), expira_epoch=time.time() + self.settings['control']['expirare_comanda_s'])
            if target == 'psim':
                command['canal_id'] = previous['canal_id']
            try:
                write_json(self.directory / f'control_{target}_cerere.json', command)
            except OSError:
                return {'mesaj': 'Comanda nu a putut fi transmisa catre Octave.'}, 503
            self.requests[target] = command
            return {'mesaj': 'Comanda transmisa; asteptare confirmare.', 'secventa': self.sequence}, 202
