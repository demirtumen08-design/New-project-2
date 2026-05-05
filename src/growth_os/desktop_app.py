from __future__ import annotations

import socket
import threading
import tkinter as tk
import webbrowser
import os
from http.server import ThreadingHTTPServer
from tkinter import messagebox, ttk

from .server import GrowthHandler
from .sitegen import generate


def free_port(preferred: int = 8090) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Uygun port bulunamadi.")


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Turkiye Gundemi Growth OS")
        self.geometry("620x360")
        self.resizable(False, False)
        self.server: ThreadingHTTPServer | None = None
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        self.status = tk.StringVar(value="Sunucu hazirlaniyor...")
        self.build_ui()
        self.after(200, self.start_server)

    def build_ui(self) -> None:
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Turkiye Gundemi Growth OS", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Haber duzenleme, yayinlama, audit ve statik site uretimi icin yerel uygulama.",
            wraplength=560,
        ).pack(anchor="w", pady=(8, 18))
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(0, 18))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Yonetim Panelini Ac", command=self.open_admin).grid(row=0, column=0, padx=(0, 10), pady=6, sticky="ew")
        ttk.Button(buttons, text="Siteyi Ac", command=self.open_site).grid(row=0, column=1, padx=(0, 10), pady=6, sticky="ew")
        ttk.Button(buttons, text="Yayinla", command=self.publish).grid(row=0, column=2, pady=6, sticky="ew")
        ttk.Button(buttons, text="Audit API", command=self.open_audit).grid(row=1, column=0, padx=(0, 10), pady=6, sticky="ew")
        ttk.Button(buttons, text="Kapat", command=self.close).grid(row=1, column=1, padx=(0, 10), pady=6, sticky="ew")
        for col in range(3):
            buttons.columnconfigure(col, weight=1)
        ttk.Separator(frame).pack(fill="x", pady=18)
        ttk.Label(
            frame,
            text=(
                "Icerik dosyalari exe yanindaki workspace klasorundedir. "
                "Panelden yaptiginiz degisiklikler JSON'a yazilir ve Yayinla ile statik siteye uygulanir."
            ),
            wraplength=560,
        ).pack(anchor="w")

    def start_server(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), GrowthHandler)
        self.server.site_at_root = os.environ.get("GROWTH_OS_SITE_AT_ROOT") == "1"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.status.set(f"Calisiyor: {self.url}")

    def open_admin(self) -> None:
        webbrowser.open(self.url + "admin")

    def open_site(self) -> None:
        webbrowser.open(self.url + "turkiye-gundemi/")

    def open_audit(self) -> None:
        webbrowser.open(self.url + "api/audit?site=medyafaresi")

    def publish(self) -> None:
        try:
            out = generate("turkiye-gundemi")
        except Exception as exc:  # noqa: BLE001 - UI message
            messagebox.showerror("Yayinlama hatasi", str(exc))
            return
        messagebox.showinfo("Yayinlandi", f"Site uretildi:\n{out}")

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
        self.destroy()


def main() -> int:
    app = DesktopApp()
    app.protocol("WM_DELETE_WINDOW", app.close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
