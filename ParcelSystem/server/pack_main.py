import threading
import socket
import uvicorn
from PyQt5 import QtWidgets
import server.server_ui as ui
from server.app.broadcaster import start_broadcast

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def start_uvicorn():
    host_ip = get_local_ip()
    start_broadcast(host=host_ip, port=8000)
    uvicorn.run("server.app.api:app", host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    t = threading.Thread(target=start_uvicorn, daemon=True)
    t.start()
    app = QtWidgets.QApplication([])
    w = ui.ServerUI()
    w.show()
    app.exec_()
