# server/app/main.py
import uvicorn
from .api import app
import socket

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    host_ip = get_local_ip()
    start_broadcast(host=host_ip, port=8000)
    uvicorn.run('server.app.api:app', host='0.0.0.0', port=8000, log_level='info')