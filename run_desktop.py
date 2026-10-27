"""Desktop launcher (Tkinter).

Double-click / run:  python run_desktop.py
- prepares the database (makemigrations + migrate + demo data on first run)
- starts the Django server
- opens the app in your browser
"""
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import scrolledtext

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MANAGE = os.path.join(BASE_DIR, "manage.py")
HOST = "127.0.0.1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # hide console on Windows

BG, PANEL, FG, ACCENT = "#0f1219", "#171c27", "#e6e9f0", "#4f8cff"


def free_port(preferred=8000):
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    return preferred


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HR Portal - Server Launcher")
        self.geometry("720x460")
        self.configure(bg=BG)
        self.proc = None
        self.port = free_port()
        self.logq = queue.Queue()

        tk.Label(self, text="HR Portal", font=("Segoe UI", 18, "bold"), bg=BG, fg=FG).pack(pady=(14, 0))
        self.status = tk.Label(self, text="Stopped", font=("Segoe UI", 11), bg=BG, fg="#ff5c5c")
        self.status.pack(pady=(0, 8))

        bar = tk.Frame(self, bg=BG)
        bar.pack()
        self.btn_start = self._button(bar, "Start Server", self.start_server)
        self.btn_open = self._button(bar, "Open in Browser", self.open_browser)
        self.btn_stop = self._button(bar, "Stop Server", self.stop_server)
        self.btn_open.config(state="disabled")
        self.btn_stop.config(state="disabled")

        self.log = scrolledtext.ScrolledText(self, height=18, bg=PANEL, fg="#9aa4b8", insertbackground=FG,
                                             relief="flat", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=14, pady=14)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._drain)
        self.after(400, self.start_server)

    def _button(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd, bg=ACCENT, fg="white", activebackground="#3b73d9",
                      activeforeground="white", relief="flat", padx=14, pady=6, font=("Segoe UI", 10, "bold"))
        b.pack(side="left", padx=6)
        return b

    # ---------- helpers ----------
    def write(self, text):
        self.logq.put(text)

    def _drain(self):
        try:
            while True:
                self.log.insert("end", self.logq.get_nowait())
                self.log.see("end")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def set_status(self, text, color):
        self.status.config(text=text, fg=color)

    def run_cmd(self, *args):
        """Run a manage.py command and stream its output to the log. Returns exit code."""
        p = subprocess.Popen([sys.executable, MANAGE, *args], cwd=BASE_DIR, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
        for line in p.stdout:
            self.write(line)
        return p.wait()

    # ---------- actions ----------
    def start_server(self):
        if self.proc and self.proc.poll() is None:
            return
        self.btn_start.config(state="disabled")
        self.set_status("Preparing database...", "#ffc107")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        for cmd in (("makemigrations", "portal"), ("migrate",), ("seed_demo",)):
            if self.run_cmd(*cmd) != 0:
                self.write("\n*** Setup failed. Did you run: pip install -r requirements.txt ?\n")
                self.after(0, lambda: (self.set_status("Error - see log", "#ff5c5c"), self.btn_start.config(state="normal")))
                return
        self.port = free_port(self.port)
        self.proc = subprocess.Popen(
            [sys.executable, MANAGE, "runserver", f"{HOST}:{self.port}", "--noreload"],
            cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._pipe_output, daemon=True).start()
        for _ in range(60):  # wait until the port answers
            with socket.socket() as s:
                if s.connect_ex((HOST, self.port)) == 0:
                    break
            time.sleep(0.5)
        self.after(0, self._server_up)

    def _server_up(self):
        self.set_status(f"Running at http://{HOST}:{self.port}", "#3ddc84")
        self.btn_open.config(state="normal")
        self.btn_stop.config(state="normal")
        self.open_browser()

    def _pipe_output(self):
        for line in self.proc.stdout:
            self.write(line)
        self.after(0, self._server_down)

    def _server_down(self):
        self.set_status("Stopped", "#ff5c5c")
        self.btn_start.config(state="normal")
        self.btn_open.config(state="disabled")
        self.btn_stop.config(state="disabled")

    def open_browser(self):
        webbrowser.open(f"http://{HOST}:{self.port}/")

    def stop_server(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def on_close(self):
        self.stop_server()
        self.destroy()


if __name__ == "__main__":
    Launcher().mainloop()
