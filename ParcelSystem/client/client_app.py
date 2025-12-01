# client/client_app.py
import sys, os, json, socket, threading, requests
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QPushButton, QTextEdit, QLabel

DISCOVERY_PORT = 37020

class DiscoveryThread(threading.Thread):
    def __init__(self, on_found):
        super().__init__(daemon=True)
        self.on_found = on_found

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', DISCOVERY_PORT))
        while True:
            try:
                data, addr = s.recvfrom(1024)
                info = json.loads(data.decode('utf-8'))
                host = info.get('host')
                port = info.get('port')
                url = f"http://{host}:{port}"
                self.on_found(url)
            except Exception:
                pass

class MainWin(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Parcel Client')
        self.layout = QVBoxLayout()
        self.lbl = QLabel('Server: (searching...)')
        self.input = QLineEdit()
        self.input.setPlaceholderText('Scan or type tracking number and press Enter')
        self.btn = QPushButton('Send')
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.layout.addWidget(self.lbl)
        self.layout.addWidget(self.input)
        self.layout.addWidget(self.btn)
        self.layout.addWidget(self.log)
        self.setLayout(self.layout)
        self.btn.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)
        self.server_url = None
        # start discovery
        t = DiscoveryThread(self.on_found)
        t.start()

    def on_found(self, url):
        if not self.server_url:
            self.server_url = url
            self.lbl.setText(f'Server: {url}')
            self.log.append(f'Found server: {url}')

    def send(self):
        tn = self.input.text().strip()
        if not tn:
            return
        if not self.server_url:
            self.log.append('Server not found. Cannot send.')
            return
        payload = {'tracking_number': tn, 'carrier': 'SPX'}
        try:
            r = requests.post(f"{self.server_url}/api/parcels", json=payload, timeout=5)
            self.log.append(f'Status: {r.status_code} {r.text}')
        except Exception as e:
            self.log.append(f'Error: {e}')
        self.input.clear()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = MainWin()
    w.show()
    sys.exit(app.exec_())