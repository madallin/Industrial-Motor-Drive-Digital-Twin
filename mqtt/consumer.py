"""Consume motor and communication notifications without issuing drive commands."""
from collections import OrderedDict, deque
import json
import threading
import time
import uuid

from .contracts import configure_client, topic
from application.iiot_config import finite_numeric


class Notifications:
    def __init__(self, limit=200):
        self.items = deque(maxlen=limit)
        self.seen = OrderedDict()
        self.limit = limit
        self.lock = threading.RLock()

    def add(self, event):
        if (not isinstance(event, dict) or event.get('schema') != 'industrial-drive.event.v1'
                or not isinstance(event.get('id'), str) or not 1 <= len(event['id']) <= 128
                or event.get('severity') not in ('INFO', 'WARN', 'ALARM')
                or any(not isinstance(event.get(key), str) or not 1 <= len(event[key]) <= 128 for key in ('source', 'code'))):
            raise ValueError('Invalid notification.')
        epoch = event.get('observed_epoch')
        if not finite_numeric(epoch) or not -5 <= time.time()-epoch <= 300:
            raise ValueError('Expired notification.')
        for key in ('value', 'sim_time_s'):
            value = event.get(key)
            if value is not None and not finite_numeric(value):
                raise ValueError('Invalid event value.')
        for key, limit in (('session_id', 200), ('origin', 64)):
            value = event.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > limit):
                raise ValueError('Invalid event metadata.')
        with self.lock:
            if event['id'] in self.seen:
                return False
            self.seen[event['id']] = True
            while len(self.seen) > self.limit * 8:
                self.seen.popitem(last=False)
            self.items.append({key: event.get(key) for key in ('id', 'source', 'origin', 'code', 'severity', 'observed_epoch', 'sim_time_s', 'session_id', 'value')} | {'acknowledged_epoch': None})
            return True

    def acknowledge(self, identifier):
        with self.lock:
            for event in self.items:
                if event['id'] == identifier:
                    event['acknowledged_epoch'] = event['acknowledged_epoch'] or time.time()
                    return True
        return False

    def snapshot(self):
        with self.lock:
            return [dict(event) for event in self.items]


class MQTTConsumer:
    def __init__(self, settings, stop_event, on_event=None):
        self.settings, self.stop_event = settings, stop_event
        self.notifications = Notifications(settings['iiot']['notifications']['max_items'])
        self.client = None
        self.previous_publisher = None
        self.previous_gap = False
        self.on_event = on_event
        self.status = {'enabled': settings['mqtt']['activ'] and settings['iiot']['notifications']['enabled'], 'connected': False, 'rejected_messages': 0,
                       'message': 'MQTT dezactivat.'}

    def local_event(self, code, severity):
        if self.settings['iiot']['notifications']['enabled']:
            event = {'schema': 'industrial-drive.event.v1', 'id': uuid.uuid4().hex,
                'source': 'mqtt', 'origin': 'service', 'observed_epoch': time.time(), 'code': code, 'severity': severity, 'level': severity}
            self.notifications.add(event)
            if self.on_event:
                self.on_event(event)

    def start(self):
        if not self.status['enabled']:
            return
        try:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='industrial-drive-observer-' + uuid.uuid4().hex[:12])
            configure_client(self.client, self.settings['mqtt'])
            self.client.on_connect, self.client.on_disconnect, self.client.on_message = self.on_connect, self.on_disconnect, self.on_message
            self.client.connect_async(self.settings['mqtt']['adresa'], self.settings['mqtt']['port'], keepalive=15)
            self.client.loop_start()
            self.status['message'] = 'Asteptare broker; reconectare automata.'
        except (ImportError, OSError, ValueError):
            self.status['message'] = 'Consumator MQTT indisponibil; verificati dependentele si conexiunea TLS.'

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.status.update(connected=False, message='Conexiune MQTT refuzata.')
            return
        subscriptions = []
        mqtt = self.settings['mqtt']
        if self.settings['iiot']['notifications']['enabled']:
            subscriptions.extend([(topic(mqtt, 'events'), 1), (topic(mqtt, 'status'), 1)])
        result = client.subscribe(subscriptions) if subscriptions else (0, None)
        self.status.update(connected=result[0] == 0, message='Conectat.' if result[0] == 0 else 'Abonarea MQTT a esuat.')
        self.local_event('MQTT_CONNECTED', 'INFO')

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        was_connected = self.status['connected']
        self.status.update(connected=False, message='Deconectat; reconectare automata.')
        if was_connected and not self.stop_event.is_set():
            self.local_event('MQTT_DISCONNECTED', 'WARN')

    def on_message(self, client, userdata, message):
        try:
            if len(message.payload) > 4096:
                raise ValueError('Oversized MQTT message.')
            payload = json.loads(message.payload, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            mqtt = self.settings['mqtt']
            if message.topic == topic(mqtt, 'events'):
                if message.retain:
                    raise ValueError('Retained events cannot be current notifications.')
                self.notifications.add(payload)
            elif message.topic == topic(mqtt, 'status'):
                gap = payload.get('event_gap') is True
                if gap and not self.previous_gap:
                    self.local_event('MQTT_EVENT_GAP', 'WARN')
                self.previous_gap = gap
                state = payload.get('serviciu')
                if state in ('DECONECTAT', 'OPRIT') and self.previous_publisher == 'CONECTAT':
                    self.local_event('MQTT_PUBLISHER_OFFLINE', 'WARN' if state == 'DECONECTAT' else 'INFO')
                self.previous_publisher = state
            else:
                raise ValueError('Unexpected notification topic.')
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
            self.status['rejected_messages'] += 1

    def state(self):
        return {'mqtt_consumer': dict(self.status), 'notifications': self.notifications.snapshot()}

    def close(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
