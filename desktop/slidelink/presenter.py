"""Built-in PDF presenter (PyMuPDF + Tk). Gives exact page counter, go-to-page, black/white screen, laser."""
import tkinter as tk


class Presenter:
    def __init__(self, root):
        self.root, self.win, self.doc, self.page = root, None, None, 0
        self.screen, self.fs, self._laser = "", False, None
        self._snap = {"open": False}

    # ---- thread-safe public API (called from the BLE thread) ----
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

    # ---- Tk-thread internals ----
    def open(self, path):
        import fitz
        self.close()
        self.doc, self.page, self.screen = fitz.open(path), 0, ""
        self.win = tk.Toplevel(self.root)
        self.win.title("SlideLink – " + path.split("/")[-1])
        self.win.geometry("1000x640")
        self.win.configure(bg="black")
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._render())
        self.win.bind("<Right>", lambda e: self._go(self.page + 1))
        self.win.bind("<Left>", lambda e: self._go(self.page - 1))
        self.win.bind("<Escape>", lambda e: self._set_fs(False))
        self.win.bind("<F5>", lambda e: self._set_fs(True))
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.focus_force()
        self._publish()

    def close(self):
        if self.win:
            self.win.destroy()
        self.win, self.doc, self.fs = None, None, False
        self._snap = {"open": False}

    def _go(self, n):
        if self.doc:
            self.page = max(0, min(len(self.doc) - 1, n))
            self.screen = ""
            self._render()

    def _set_fs(self, on):
        if self.win:
            self.fs = on
            self.win.attributes("-fullscreen", on)
            self.canvas.config(cursor="none" if on else "")
            self.win.after(150, self._render)

    def _toggle(self, c):
        self.screen = "" if self.screen == c else c
        self._render()

    def _set_laser(self, pos):
        self._laser = pos
        self._draw_laser()

    def _draw_laser(self):
        if not self.win:
            return
        self.canvas.delete("laser")
        if self._laser and not self.screen:
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            x, y = self._laser[0] * w, self._laser[1] * h
            self.canvas.create_oval(x - 9, y - 9, x + 9, y + 9, fill="#ff2a2a", outline="#ff9a9a", tags="laser")

    def _render(self):
        if not (self.win and self.doc):
            return
        import fitz
        self.canvas.delete("all")
        w, h = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        if self.screen:
            self.canvas.configure(bg="black" if self.screen == "b" else "white")
        else:
            self.canvas.configure(bg="black")
            pg = self.doc[self.page]
            zoom = min(w / pg.rect.width, h / pg.rect.height)
            pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            self._img = tk.PhotoImage(data=pix.tobytes("ppm"))
            self.canvas.create_image(w // 2, h // 2, image=self._img)
        self._draw_laser()
        self._publish()

    def _publish(self):
        self._snap = {"open": True, "page": self.page + 1, "pages": len(self.doc), "screen": self.screen, "fs": self.fs}
