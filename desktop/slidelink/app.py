"""SlideLink Desktop Receiver – small Tk window; BLE runs in a background thread."""
import asyncio, platform, queue, socket, subprocess, threading
import tkinter as tk
from tkinter import filedialog, messagebox
from .session import PinManager, PairStore, Session
from .controller import Controller
from .presenter import Presenter
from .vlc import Vlc, find_vlc
from .ble_server import BleServer
from .web import WebServer, local_ip, PORT
from .display import enable_high_dpi, dpi_scale

HINTS = {
    "Windows": "Turn Bluetooth ON in Settings > Bluetooth & devices. Windows 10 (1703+) or 11 is required.",
    "Linux": "Run: sudo systemctl enable --now bluetooth  and  rfkill unblock bluetooth",
}


def bt_hint():
    if platform.system() == "Linux":
        try:
            out = subprocess.run(["rfkill", "list", "bluetooth"], capture_output=True, text=True).stdout
            if not out.strip():
                return "No Bluetooth adapter found."
            if "Soft blocked: yes" in out:
                return "Bluetooth is turned off. Turn it on in system settings."
        except Exception:
            pass
    return HINTS.get(platform.system(), "")


def main():
    enable_high_dpi()          # must run before the first Tk window: keeps slides sharp on scaled displays
    root = tk.Tk()
    root.title("SlideLink Desktop")
    scale = dpi_scale(root)
    root.geometry(f"{int(440 * scale)}x{int(610 * scale)}")
    events = queue.Queue()
    pins, store, vlc, presenter = PinManager(), PairStore(), Vlc(), Presenter(root)
    ctrl = Controller(presenter, vlc)
    session = Session(store, pins, ctrl.handle, lambda *a: events.put(a))
    name = "SlideLink-" + socket.gethostname()[:12]
    server = BleServer(name, session, ctrl, lambda *a: events.put(a))
    web = WebServer(ctrl, pins, store, on_event=lambda *a: events.put(a))
    try:
        web.start()
        url = f"http://{local_ip()}:{PORT}"
    except OSError as e:
        url = f"Web remote unavailable (port {PORT} busy)"

    tk.Label(root, text="SlideLink", font=("Helvetica", 22, "bold")).pack(pady=(14, 0))
    status = tk.Label(root, text="Starting Bluetooth…", font=("Helvetica", 12)); status.pack(pady=4)
    tk.Label(root, text="Pairing code (enter it on your phone the first time):").pack(pady=(14, 0))
    pin_lbl = tk.Label(root, font=("Courier", 34, "bold")); pin_lbl.pack()
    tk.Label(root, text="iPhone / browser remote – open this address on the phone:").pack(pady=(10, 0))
    url_lbl = tk.Label(root, text=url, font=("Helvetica", 14, "bold"), fg="#1a4fd6"); url_lbl.pack()
    info = tk.Label(root, text="", wraplength=int(380 * scale), fg="#b00020"); info.pack(pady=4)

    def refresh_pin():
        pin_lbl.config(text=" ".join(pins.pin[i:i + 3] for i in (0, 3)))

    def new_code():
        pins.new(); refresh_pin()

    def open_pdf():
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            try:
                presenter.open(p)
            except Exception as e:
                messagebox.showerror("Cannot open PDF", str(e))

    def open_video():
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov")])
        if p and not vlc.launch(p):
            messagebox.showerror("VLC not found", "Please install VLC Media Player (videolan.org).")

    for text, cmd in (("Open PDF presentation", open_pdf), ("Open MP4 video (VLC)", open_video),
                      ("Laser pointer settings…", presenter.open_laser_panel), ("New pairing code", new_code)):
        tk.Button(root, text=text, command=cmd, width=28).pack(pady=3)
    tk.Button(root, text="Quit", command=root.destroy, width=28).pack(pady=3)
    tk.Label(root, text="Close this window to hide it; the receiver keeps running.\nTip: minimise it, then use your phone.",
             fg="gray").pack(pady=8)
    tk.Label(root, text="Developed by youcefkebbab", fg="gray").pack(pady=(0, 6))
    if not find_vlc():
        info.config(text="VLC not found – video control needs VLC Media Player.")

    def run_ble():
        try:
            asyncio.run(server.run())
        except Exception as e:  # noqa
            events.put(("error", f"{e}\n{bt_hint()}"))

    threading.Thread(target=run_ble, daemon=True).start()

    def poll():
        while not events.empty():
            kind, *rest = events.get()
            if kind == "advertising":
                status.config(text=f"● Ready – visible as “{rest[0]}”", fg="#1a7f37")
            elif kind == "connected":
                status.config(text=f"● Connected to {rest[0]}", fg="#1a7f37"); refresh_pin()
            elif kind == "error":
                status.config(text="● Bluetooth problem", fg="#b00020"); info.config(text=rest[0])
        import time
        if time.time() - web.last_seen < 3:
            status.config(text="● Phone connected (browser)", fg="#1a7f37")
        elif "browser" in status.cget("text"):
            status.config(text="● Ready – waiting for phone", fg="#1a7f37")
        if pins.valid() is False:
            new_code()
        root.after(300, poll)

    refresh_pin(); poll()
    root.protocol("WM_DELETE_WINDOW", root.iconify)
    root.mainloop()
