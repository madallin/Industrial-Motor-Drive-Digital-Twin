"""Publish live telemetry over optional MQTT without exposing drive commands."""
import json
import threading
import time
from .contracts import configure_client, topic


class MQTTPublisher:
    def __init__(self, settings, store, stop_event):
        self.settings = settings
        self.store = store
        self.stop_event = stop_event
        self.client = None
        self.connected = threading.Event()
        self.thread = None
        self.last_published = {}
        self.events = None
        self.event_cursor = None
        self.state = {'activ': settings['activ'], 'conectat': False, 'mesaj': 'MQTT dezactivat.'}

    def start(self):
        if not self.settings['activ']:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.state['mesaj'] = 'Lipseste paho-mqtt: py -3 -m pip install -r mqtt/requirements.txt'
            print(self.state['mesaj'], flush=True)
            return
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='industrial-drive-' + self.store.instance_id[:16])
        try:
            configure_client(self.client, self.settings)
        except (OSError, ValueError):
            self.state['mesaj'] = 'Configuratia MQTT/TLS nu permite conectarea.'
            return
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.will_set(self.topic('status'), json.dumps({'serviciu': 'DECONECTAT', 'surse': {}, 'actualizat_epoch': time.time()}), qos=1, retain=True)
        self.client.connect_async(self.settings['adresa'], self.settings['port'], keepalive=15)
        self.client.loop_start()
        self.state['mesaj'] = 'Asteptare broker; reconectare automata.'
        self.thread = threading.Thread(target=self.run, name='publicare-mqtt', daemon=True)
        self.thread.start()

    def topic(self, suffix):
        return topic(self.settings, suffix)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.state['mesaj'] = 'Brokerul a refuzat conexiunea MQTT.'
            self.connected.clear()
        else:
            self.state['mesaj'] = 'Broker MQTT conectat.'
            self.connected.set()
            self.last_published.clear()
            self.event_cursor = None
            print(self.state['mesaj'], flush=True)
        self.state['conectat'] = self.connected.is_set()

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected.clear()
        self.state.update(conectat=False, mesaj='MQTT deconectat; reconectare automata.')

    def publish(self, suffix, payload, qos=0, retain=False):
        if self.connected.is_set():
            return self.client.publish(self.topic(suffix), json.dumps(payload, allow_nan=False), qos=qos, retain=retain)
        return None

    def run(self):
        while not self.stop_event.wait(0.5):
            try:
                if self.events and self.connected.is_set():
                    events, gap = self.events.since(self.event_cursor, 20)
                    self.state['event_gap'] = gap
                    for event in events:
                        result = self.publish('events', event, qos=1)
                        if result is None or result.rc != 0:
                            break
                        self.event_cursor = event['sequence']
                sources = {}
                alarms = {}
                for source in ('psim',):
                    data = self.store.live_source(source)
                    sources[source] = data['achizitie']
                    alarms[source] = {'achizitie': data['achizitie'], 'conditii': data['alarme'] if data['achizitie'] == 'ACTIV' else None}
                    latest = data.get('ultim')
                    if data['achizitie'] != 'ACTIV' or not latest:
                        continue
                    token = (data['id'], latest['t'])
                    if self.last_published.get(source) == token:
                        continue
                    result = self.publish('telemetry', {
                        'schema': 'industrial-drive.telemetrie.v2', 'sursa': source,
                        'context': 'live', 'sesiune': data['id'], 'achizitie': 'ACTIV',
                        'inregistrat_epoch': data['metadate'].get('esantion_epoch'),
                        'unitati': data['metadate'].get('unitati'), 'valori': latest,
                        'origine': 'simulare_electrica_PSIM'})
                    if result is not None and result.rc == 0:
                        self.last_published[source] = token
                self.publish('status', {'serviciu': 'CONECTAT', 'surse': sources, 'actualizat_epoch': time.time(), 'event_gap': self.state.get('event_gap', False)}, qos=1, retain=True)
                alarm_token = json.dumps(alarms, sort_keys=True)
                if self.last_published.get('alarme') != alarm_token:
                    result = self.publish('alarms', {'actualizat_epoch': time.time(), 'surse': alarms}, qos=1)
                    if result is not None and result.rc == 0:
                        self.last_published['alarme'] = alarm_token
            except (OSError, ValueError, TypeError) as error:
                self.state['mesaj'] = 'Date MQTT temporar indisponibile: ' + type(error).__name__

    def close(self):
        if self.thread:
            self.thread.join(timeout=2)
        if self.client:
            publication = self.publish('status', {'serviciu': 'OPRIT', 'surse': {}, 'actualizat_epoch': time.time()}, qos=1, retain=True)
            if publication:
                try:
                    publication.wait_for_publish(timeout=1)
                except (RuntimeError, ValueError):
                    pass
            self.client.disconnect()
            self.client.loop_stop()
