# server/server_ui.py
import sys, socket, threading, requests, os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QListWidget, QMessageBox
from PyQt5.QtCore import Qt

API_BASE = "http://127.0.0.1:8000"

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

class ServerUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parcel Server UI")
        self.resize(800, 500)

        self.layout = QVBoxLayout()
        top = QHBoxLayout()
        self.lbl_ip = QLabel(f"Server: {get_local_ip()}:8000")
        top.addWidget(self.lbl_ip)
        top.addStretch()
        self.btn_refresh = QPushButton("Refresh list")
        self.btn_backup = QPushButton("Backup DB")
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_backup)
        self.layout.addLayout(top)

        mid = QHBoxLayout()
        left = QVBoxLayout()
        self.list_widget = QListWidget()
        left.addWidget(QLabel("Recent parcels"))
        left.addWidget(self.list_widget)
        mid.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel("Search by tracking"))
        self.input_search = QLineEdit()
        self.btn_search = QPushButton("Search")
        right.addWidget(self.input_search)
        right.addWidget(self.btn_search)
        right.addWidget(QLabel("Parcel details"))
        self.text_details = QTextEdit()
        self.text_details.setReadOnly(True)
        right.addWidget(self.text_details)
        self.btn_pickup = QPushButton("Mark as PICKED_UP")
        right.addWidget(self.btn_pickup)
        mid.addLayout(right, 3)

        self.layout.addLayout(mid)
        self.setLayout(self.layout)

        # signals
        self.btn_refresh.clicked.connect(self.load_list)
        self.btn_search.clicked.connect(self.search)
        self.list_widget.itemClicked.connect(self.show_from_list)
        self.btn_pickup.clicked.connect(self.pickup)
        self.btn_backup.clicked.connect(self.backup_db)

        self.load_list()

    def load_list(self):
        try:
            r = requests.get(API_BASE + "/api/parcels", timeout=5)
            if r.status_code == 200:
                self.list_widget.clear()
                for p in r.json():
                    text = f"{p['queue_number'] or ''} | {p['tracking_number']} | {p['status']}"
                    self.list_widget.addItem(text)
                self.text_details.setPlainText(f"Loaded {len(r.json())} parcels.")
            else:
                self.text_details.setPlainText(f"Error loading list: {r.status_code} {r.text}")
        except Exception as e:
            self.text_details.setPlainText(f"Error: {e}")

    def show_from_list(self, item):
        # extract tracking from list item
        try:
            parts = item.text().split("|")
            tracking = parts[1].strip()
            self.show_parcel(tracking)
        except Exception as e:
            self.text_details.setPlainText(str(e))

    def search(self):
        tracking = self.input_search.text().strip()
        if not tracking:
            QMessageBox.information(self, "Info", "กรุณากรอก tracking number")
            return
        self.show_parcel(tracking)

    def show_parcel(self, tracking):
        try:
            r = requests.get(API_BASE + f"/api/parcels/{tracking}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                pretty = "\n".join([f"{k}: {v}" for k, v in data.items()])
                self.text_details.setPlainText(pretty)
            else:
                self.text_details.setPlainText(f"Not found: {r.status_code} {r.text}")
        except Exception as e:
            self.text_details.setPlainText(f"Error: {e}")

    def pickup(self):
        # pick based on the current details shown (attempt read tracking)
        txt = self.text_details.toPlainText()
        if "tracking_number" in txt:
            # crude parsing
            for line in txt.splitlines():
                if line.startswith("tracking_number"):
                    tracking = line.split(":",1)[1].strip()
                    break
            else:
                QMessageBox.warning(self, "Warning", "Cannot parse tracking")
                return
        else:
            tracking, ok = QInputDialog.getText(self, "Pickup", "Enter tracking:")
            if not ok or not tracking:
                return
        try:
            r = requests.post(API_BASE + f"/api/parcels/{tracking}/pickup", timeout=5)
            if r.status_code == 200:
                QMessageBox.information(self, "OK", "Parcel marked as PICKED_UP")
                self.load_list()
            else:
                QMessageBox.warning(self, "Error", f"{r.status_code} {r.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def backup_db(self):
        # perform a simple file copy of DB (path used by server)
        # server stores DB at PROGRAMDATA\ParcelSystem\parcel.db by default
        try:
            import shutil, datetime
            base = os.getenv('PROGRAMDATA') or os.path.join('.', 'ParcelSystem')
            src = os.path.join(base, 'parcel.db')
            if not os.path.exists(src):
                QMessageBox.warning(self, "Warning", f"DB file not found: {src}")
                return
            dst_dir = os.path.join(base, 'backups')
            os.makedirs(dst_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            dst = os.path.join(dst_dir, f'parcel_{ts}.db')
            shutil.copy2(src, dst)
            QMessageBox.information(self, "Backup", f"Backup saved: {dst}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = ServerUI()
    w.show()
    sys.exit(app.exec_())
