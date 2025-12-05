# server/launcher.py
import subprocess, sys, os, signal
import tkinter as tk
from tkinter import scrolledtext

PY = sys.executable

class App:
    def __init__(self, root):
        self.root = root
        root.title("ParcelServer Launcher")
        self.proc = None
        tk.Button(root, text="Start Server", command=self.start).pack(fill='x')
        tk.Button(root, text="Stop Server", command=self.stop).pack(fill='x')
        tk.Button(root, text="Open Admin UI", command=self.open_ui).pack(fill='x')
        self.log = scrolledtext.ScrolledText(root, height=12)
        self.log.pack(fill='both', expand=True)

    def start(self):
        if self.proc and self.proc.poll() is None:
            self.log.insert('end', 'Server already running\n'); return
        # start uvicorn programmatically
        self.proc = subprocess.Popen([PY, "-m", "server.app.main"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.root.after(100, self.poll_output)
        self.log.insert('end', 'Starting server...\n')

    def poll_output(self):
        if not self.proc: return
        line = self.proc.stdout.readline()
        if line:
            self.log.insert('end', line); self.log.see('end')
        if self.proc.poll() is None:
            self.root.after(100, self.poll_output)
        else:
            self.log.insert('end', f'Process exited {self.proc.returncode}\n')

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.log.insert('end','Stopping server...\n')
        else:
            self.log.insert('end','Server not running\n')

    def open_ui(self):
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000/admin")

if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
