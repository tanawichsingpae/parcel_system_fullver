# server/app/broadcaster.py
# simple UDP broadcaster for auto-discovery
import socket
import json
import threading
import time

BROADCAST_PORT = 37020
BROADCAST_INTERVAL = 5.0

def start_broadcast(host='127.0.0.1', port=8000, service_name='parcel-server'):
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = json.dumps({'service': service_name, 'host': host, 'port': port})
        while True:
            try:
                sock.sendto(payload.encode('utf-8'), ('<broadcast>', BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(BROADCAST_INTERVAL)
    t = threading.Thread(target=run, daemon=True)
    t.start()