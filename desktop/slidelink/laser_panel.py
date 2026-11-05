"""Laser Pointer Settings panel: enable switch, thickness slider with live preview, value, reset."""
import tkinter as tk

from .render import laser_diameter
from .settings import LASER_DEFAULT, LASER_MAX, LASER_MIN


class LaserPanel:
    def __init__(self, root, presenter):
        self.p = presenter
        self.win = tk.Toplevel(root)
        self.win.title("Laser pointer")
        self.win.resizable(False, False)
        self.enabled = tk.BooleanVar(value=presenter.settings.laser_enabled)
        tk.Checkbutton(self.win, text="Laser pointer enabled", variable=self.enabled,
                       command=lambda: presenter.set_laser_enabled(self.enabled.get())).pack(anchor="w", padx=14, pady=(12, 4))
        self.preview = tk.Canvas(self.win, width=340, height=150, bg="#f4f4f4", highlightthickness=1)
        self.preview.pack(padx=14, pady=6)
        row = tk.Frame(self.win); row.pack(fill="x", padx=14)
        tk.Label(row, text="Thin").pack(side="left")
        self.scale = tk.Scale(row, from_=LASER_MIN, to=LASER_MAX, orient="horizontal", length=250, showvalue=False,
                              command=self._on_scale)
        self.scale.pack(side="left", fill="x", expand=True, padx=6)
        tk.Label(row, text="Thick").pack(side="left")
        self.value = tk.Label(self.win, font=("Helvetica", 12, "bold")); self.value.pack(pady=(4, 0))
        tk.Label(self.win, fg="gray", text="Preview is the size the audience sees on this screen.\n"
                 "Thickness scales with screen height, so it looks the same on any projector.").pack(padx=14)
        tk.Button(self.win, text="Reset to default", command=presenter.reset_laser_size).pack(pady=(6, 12))
        presenter._listeners.append(self.sync)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self._guard = False
        self.sync()

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def raise_(self):
        self.win.deiconify(); self.win.lift(); self.win.focus_force()

    def _close(self):
        if self.sync in self.p._listeners:
            self.p._listeners.remove(self.sync)
        self.win.destroy()

    def _on_scale(self, v):
        if not self._guard:
            self.p.set_laser_size(int(float(v)))          # live: applied on every slider step

    def sync(self):
        if not self.alive():
            return
        s = self.p.settings
        self._guard = True
        self.scale.set(s.laser_size)
        self._guard = False
        self.enabled.set(s.laser_enabled)
        self.value.config(text=f"Thickness: {s.laser_size}   (default {LASER_DEFAULT}, range {LASER_MIN}–{LASER_MAX})")
        screen_h = self.win.winfo_screenheight()
        self._img = self.p.sprite_for(laser_diameter(s.laser_size, screen_h))   # keep a reference
        self.preview.delete("all")
        self.preview.create_image(170, 75, image=self._img)
