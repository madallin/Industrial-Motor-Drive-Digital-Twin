"""One topic map and TLS policy for all application MQTT clients."""
import os

TOPICS = {'telemetry': 'psim/telemetrie', 'status': 'stare', 'alarms': 'alarme',
          'events': 'events'}


def topic(settings, name):
    return settings['prefix'].strip('/') + '/' + TOPICS[name]


def configure_client(client, settings):
    client.max_queued_messages_set(20)
    client.max_inflight_messages_set(10)
    client.reconnect_delay_set(1, 10)
    username = os.getenv('IDRIVE_MQTT_USER')
    if settings['adresa'] not in ('localhost', '127.0.0.1', '::1') and (not settings.get('tls') or not username):
        raise ValueError('Brokerul extern necesita TLS si autentificare.')
    if username:
        client.username_pw_set(username, os.getenv('IDRIVE_MQTT_PASSWORD'))
    if settings.get('tls'):
        client.tls_set(ca_certs=os.getenv('IDRIVE_MQTT_CA_FILE') or None)
