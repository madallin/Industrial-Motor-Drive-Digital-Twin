"""Upgrade the existing local HTTP socket using websockets' Sans-I/O handshake."""
import json
import time


def serve_stream(handler, window_seconds):
    hub = handler.server.telemetry
    if not hub.settings['enabled']:
        return handler.respond({'mesaj': 'Flux WebSocket dezactivat.'}, 503)
    origin = f'http://127.0.0.1:{handler.server.server_port}'
    if handler.headers.get('Origin') != origin:
        return handler.respond({'mesaj': 'Origine WebSocket nepermisa.'}, 403)
    try:
        from websockets.server import ServerProtocol
        from websockets.sync.server import ServerConnection
        from websockets.exceptions import ConnectionClosed, InvalidHandshake
    except ImportError:
        return handler.respond({'mesaj': 'WebSocket indisponibil; se foloseste HTTP.'}, 503)
    if not hub.slots.acquire(blocking=False):
        return handler.respond({'mesaj': 'Prea multe conexiuni de monitorizare.'}, 503)
    connection = None
    try:
        protocol = ServerProtocol(origins=[origin], max_size=2048)
        # BaseHTTPRequestHandler consumed the HTTP headers. Feed those same
        # bytes into the library, which validates and answers the handshake.
        raw = handler.requestline + '\r\n' + ''.join(f'{key}: {value}\r\n' for key, value in handler.headers.raw_items()) + '\r\n'
        protocol.receive_data(raw.encode('latin-1'))
        request = protocol.events_received()[0]
        connection = ServerConnection(handler.connection, protocol, max_queue=1,
                                      ping_interval=5, ping_timeout=5, close_timeout=1)
        connection.process_event(request)
        connection.handshake()
        if protocol.handshake_exc:
            return
        handler.close_connection = True
        connection.start_keepalive()
        with hub.lock:
            hub.windows[handler.connection] = window_seconds
        cursor, revision = None, 0
        while not hub.stop_event.is_set():
            try:
                connection.recv(timeout=0)
            except TimeoutError:
                pass
            else:
                connection.close(1008, 'Telemetry only; use the local HTTP command API.')
                break
            frame = hub.frame(cursor, revision, window_seconds)
            if frame:
                with hub.lock:
                    hub.clients[handler.connection] = time.monotonic()
                connection.send(json.dumps(frame, allow_nan=False, separators=(',', ':')))
                with hub.lock:
                    hub.clients[handler.connection] = 0
                if frame['event_gap']:
                    connection.close(1013, 'Event journal overrun; resynchronize over HTTP.')
                    break
                cursor, revision = frame['cursor'], frame['revision']
            hub.stop_event.wait(hub.settings['interval_s'])
    except (OSError, ValueError, IndexError, ConnectionClosed, InvalidHandshake):
        pass
    finally:
        with hub.lock:
            hub.clients.pop(handler.connection, None)
            hub.windows.pop(handler.connection, None)
        if connection:
            connection.close()
        hub.slots.release()
