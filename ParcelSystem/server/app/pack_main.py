# server/pack_main.py
import threading
import time
from PyQt5 import QtWidgets
import server.app.main as srv
import server.server_ui as ui

def start_uvicorn():
    # call the same startup as when you run python -m server.app.main
    srv_main = __import__('server.app.main', fromlist=['*'])
    # this will call start_broadcast and run uvicorn blocking, so run in thread
    import uvicorn
    import socket
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        except:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    host_ip = get_local_ip()
    from server.app.broadcaster import start_broadcast
    start_broadcast(host=host_ip, port=8000)
    uvicorn.run('server.app.api:app', host='0.0.0.0', port=8000, log_level='info')

if __name__ == '__main__':
    t = threading.Thread(target=start_uvicorn, daemon=True)
    t.start()
    app = QtWidgets.QApplication([])
    w = ui.ServerUI()
    w.show()
    app.exec_()
