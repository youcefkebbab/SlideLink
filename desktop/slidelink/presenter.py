"""Built-in PDF presenter (PyMuPDF + Tk). Gives exact page counter, go-to-page, black/white screen, laser.

Quality design (see render.py): every page is rasterised from the PDF's original vector content at the
exact pixel size of the canvas (physical pixels - the process is DPI-aware, see display.py), kept as raw
uncompressed RGB, cached at full resolution, and the next pages are pre-rendered in the background.
While a page is still being rendered the previous sharp slide stays on screen; a blurry upscaled preview
is never shown.
"""
import base64, queue, time
import tkinter as tk

from .display import dpi_scale
from .render import (LRUBytes, PageRenderer, fit_size, laser_diameter, laser_sprite, pdf_info, png_rgba,
                     smooth)
from .settings import LASER_DEFAULT, Settings, clamp_laser

PREFETCH_AHEAD, PREFETCH_BEHIND = 3, 1


class Presenter:
    def __init__(self, root, settings=None):
        self.root, self.win, self.page = root, None, 0
        self.settings = settings or Settings()
        self.screen, self.fs = "", False
        self.renderer = self.cache = None
        self.count, self.sizes, self._epoch = 0, [], 0
        self._img = None
        self._lz_target = None           # (x, y) in 0..1, or None when the phone released the laser
        self._lz_pos, self._lz_item, self._lz_img, self._lz_last = (0.5, 0.5), None, None, 0.0
        self._lz_anim = self._lz_rebuild = self._resize_job = self._poll_job = None
        self._sprites = {}
        self._listeners = []             # laser panel(s) to refresh when a setting changes
        self.panel = None
        self.error = None
        self._snap = {"open": False}

    # ---- thread-safe public API (called from the BLE / web threads) ----
    def snapshot(self):
        return self._snap

    def _ui(self, fn, *a):
        self.root.after(0, lambda: fn(*a))

    def next(self): self._ui(self._go, self.page + 1)
    def prev(self): self._ui(self._go, self.page - 1)
    def first(self): self._ui(self._go, 0)
    def last(self): self._ui(self._go, 10**6)
    def goto(self, n): self._ui(self._go, n - 1)
    def start(self): self._ui(self._set_fs, True)
    def exit(self): self._ui(self._set_fs, False)
    def fullscreen(self): self._ui(self._set_fs, not self.fs)
    def black(self): self._ui(self._toggle, "b")
    def white(self): self._ui(self._toggle, "w")
    def laser(self, x, y, on): self._ui(self._set_laser, (x, y) if on else None)
    def set_laser_size(self, v): self._ui(self._apply_laser_size, clamp_laser(v))
    def reset_laser_size(self): self._ui(self._apply_laser_size, LASER_DEFAULT)
    def set_laser_enabled(self, on): self._ui(self._apply_laser_enabled, bool(on))
    def open_laser_panel(self): self._ui(self._show_panel)

    # ---- Tk-thread internals ----
    def open(self, path):
        self.close()
        try:
            self.count, self.sizes = pdf_info(path)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self._snap = {"open": False}
            raise
        self.error, self.page, self.screen, self._epoch = None, 0, "", 0
        self.cache = LRUBytes(self.settings.cache_mb * 1024 * 1024)
        self.renderer = PageRenderer(path)
        s = dpi_scale(self.root)
        self.win = tk.Toplevel(self.root)
        self.win.title("SlideLink – " + path.replace("\\", "/").split("/")[-1])
        self.win.geometry(f"{int(1000 * s)}x{int(640 * s)}")
        self.win.configure(bg="black")
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._schedule_render())
        for keys, fn in ((("<Right>", "<Next>", "<space>"), lambda: self._go(self.page + 1)),
                         (("<Left>", "<Prior>"), lambda: self._go(self.page - 1)),
                         (("<Home>",), lambda: self._go(0)), (("<End>",), lambda: self._go(10**6)),
                         (("<Escape>",), lambda: self._set_fs(False)), (("<F5>",), lambda: self._set_fs(True)),
                         (("<f>", "<F11>"), lambda: self._set_fs(not self.fs)),
                         (("<b>",), lambda: self._toggle("b")), (("<w>",), lambda: self._toggle("w")),
                         (("<l>",), self._show_panel)):
            for k in keys:
                self.win.bind(k, lambda e, fn=fn: fn())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.focus_force()
        self._poll_results()
        self._publish()

    def close(self):
        for job in (self._lz_anim, self._lz_rebuild, self._resize_job, self._poll_job):
            if job:
                try: self.root.after_cancel(job)
                except Exception: pass
        self._lz_anim = self._lz_rebuild = self._resize_job = self._poll_job = None
        if self.renderer:
            self.renderer.close()
        if self.win:
            self.win.destroy()
        self.win = self.renderer = self.cache = self._img = self._lz_item = self._lz_img = None
        self.fs, self._lz_target = False, None
        self._snap = {"open": False}

    def _go(self, n):
        if self.renderer:
            self.page = max(0, min(self.count - 1, n))
            self.screen = ""
            self._render()

    def _set_fs(self, on):
        if self.win:
            self.fs = on
            self.win.attributes("-fullscreen", on)
            self.canvas.config(cursor="none" if on else "")
            self._schedule_render(150)

    def _toggle(self, c):
        self.screen = "" if self.screen == c else c
        self._render()

    # ---- page rendering ----
    def _schedule_render(self, delay=120):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(delay, self._render)

    def _canvas_px(self):
        return max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)

    def _target(self, page, w, h):
        pw, ph = self.sizes[page]
        return fit_size(pw, ph, w, h)

    def _render(self):
        self._resize_job = None
        if not (self.win and self.renderer):
            return
        w, h = self._canvas_px()
        self._epoch += 1
        self.renderer.set_epoch(self._epoch)
        if self.screen:
            self.canvas.configure(bg="black" if self.screen == "b" else "white")
            self.canvas.delete("page")
            self._img = None
        else:
            self.canvas.configure(bg="black")
            tw, th = self._target(self.page, w, h)
            img = self.cache.get((self.page, tw, th))
            if img is not None:
                self._show(img)
            else:                         # previous sharp image stays until this one is ready
                self.renderer.request(self.page, tw, th, 0, self._epoch)
            order = [self.page + d for d in range(1, PREFETCH_AHEAD + 1)] + \
                    [self.page - d for d in range(1, PREFETCH_BEHIND + 1)]
            for i, p in enumerate(q for q in order if 0 <= q < self.count):
                pw, ph = self._target(p, w, h)
                if (p, pw, ph) not in self.cache:
                    self.renderer.request(p, pw, ph, 1 + i, self._epoch, prefetch=True)
        self._place_laser(reset=True)
        self._publish()

    def _show(self, img):
        w, h = self._canvas_px()
        x, y = (w - img.width()) // 2, (h - img.height()) // 2     # whole pixels -> 1:1, no resampling
        self.canvas.delete("page")
        self.canvas.create_image(x, y, image=img, anchor="nw", tags="page")
        self.canvas.tag_lower("page")
        self._img = img

    def _poll_results(self):
        if not self.renderer:
            return
        key = size = ppm = err = None
        try:
            key, size, ppm, err = self.renderer.results.get_nowait()   # one per tick keeps the UI responsive
        except queue.Empty:
            pass
        if key is None and err is not None:
            self.error = f"{type(err).__name__}: {err}"
        elif key is not None:
            if err is not None:
                self.error = f"{type(err).__name__}: {err}"
            elif self.cache is not None:
                img = tk.PhotoImage(data=ppm)
                self.cache.put(key, img, size[0] * size[1] * 4)
                if not self.screen and key[0] == self.page:
                    w, h = self._canvas_px()
                    if key == (self.page, *self._target(self.page, w, h)):
                        self._show(img)
                        self._place_laser(reset=True)
        self._poll_job = self.root.after(5 if key else 15, self._poll_results)

    # ---- laser pointer ----
    def sprite_for(self, diameter):
        """PhotoImage (RGBA, anti-aliased) for a dot of the given pixel diameter; cached."""
        k = round(diameter * 2) / 2
        if k not in self._sprites:
            if len(self._sprites) > 12:
                self._sprites.pop(next(iter(self._sprites)))
            n, rgba = laser_sprite(k)
            self._sprites[k] = tk.PhotoImage(data=base64.b64encode(png_rgba(n, n, rgba)))
        return self._sprites[k]

    def _lz_diameter(self):
        return laser_diameter(self.settings.laser_size, self.canvas.winfo_height())

    def _set_laser(self, pos):
        if not self.win:
            return
        if pos is None or not self.settings.laser_enabled:
            self._lz_target = None
            if self._lz_item:
                self.canvas.itemconfigure(self._lz_item, state="hidden")
            return
        if self._lz_target is None:       # (re)appear exactly where the finger is
            self._lz_pos = pos
        self._lz_target = pos
        self._place_laser()
        if self._lz_anim is None:
            self._lz_last = time.monotonic()
            self._lz_anim = self.root.after(8, self._animate)

    def _place_laser(self, reset=False):
        if not (self.win and self._lz_target and self.settings.laser_enabled and not self.screen):
            if self._lz_item and self.win:
                self.canvas.itemconfigure(self._lz_item, state="hidden")
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._lz_img = self.sprite_for(self._lz_diameter())
        if self._lz_item is None or not self.canvas.type(self._lz_item):
            self._lz_item = self.canvas.create_image(0, 0, image=self._lz_img, tags="laser")
        else:
            self.canvas.itemconfigure(self._lz_item, image=self._lz_img, state="normal")
        self.canvas.coords(self._lz_item, self._lz_pos[0] * w, self._lz_pos[1] * h)
        self.canvas.tag_raise(self._lz_item)

    def _animate(self):
        self._lz_anim = None
        if not (self.win and self._lz_target):
            return
        now = time.monotonic()
        dt, self._lz_last = now - self._lz_last, now
        x, y = smooth(self._lz_pos[0], self._lz_target[0], dt), smooth(self._lz_pos[1], self._lz_target[1], dt)
        self._lz_pos = (x, y)
        self._place_laser()
        if abs(x - self._lz_target[0]) + abs(y - self._lz_target[1]) > 0.0004:
            self._lz_anim = self.root.after(8, self._animate)
        else:
            self._lz_pos = self._lz_target

    def _apply_laser_size(self, v):
        self.settings.laser_size = v
        self.settings.save()
        if self._lz_rebuild is None:      # debounce: sprite generation is the only costly step
            self._lz_rebuild = self.root.after(25, self._rebuild_laser)
        self._publish()
        self._notify()

    def _rebuild_laser(self):
        self._lz_rebuild = None
        self._place_laser()
        self._notify()

    def _apply_laser_enabled(self, on):
        self.settings.laser_enabled = on
        self.settings.save()
        if not on:
            self._set_laser(None)
        self._publish()
        self._notify()

    def _notify(self):
        for fn in list(self._listeners):
            try: fn()
            except Exception: self._listeners.remove(fn)

    def _show_panel(self):
        from .laser_panel import LaserPanel
        if self.panel is None or not self.panel.alive():
            self.panel = LaserPanel(self.root, self)
        self.panel.raise_()

    def _publish(self):
        base = {"laser_size": self.settings.laser_size, "laser_enabled": self.settings.laser_enabled}
        if self.renderer:
            self._snap = {"open": True, "page": self.page + 1, "pages": self.count, "screen": self.screen,
                          "fs": self.fs, **base}
        else:
            self._snap = {"open": False}
