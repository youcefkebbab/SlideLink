"""Rendering pipeline (no Tk): exact-size PDF rasterisation, LRU cache, laser sprite.

Pages are rasterised by MuPDF straight from the PDF's vector content at the exact
pixel size they will be displayed - never by enlarging a smaller bitmap - and are
kept as raw uncompressed RGB (PPM). Nothing here uses JPEG or lossy scaling.
"""
import math, queue, struct, threading, zlib
from collections import OrderedDict

try:
    import pymupdf as fitz
except ImportError:                       # older PyMuPDF
    import fitz

MAX_SIDE, MAX_PIXELS = 16384, 120_000_000


def fit_size(pw, ph, vw, vh):
    """Largest size with the page's aspect ratio that fits the viewport (pixels)."""
    s = min(vw / pw, vh / ph)
    w, h = pw * s, ph * s
    cap = min(1.0, MAX_SIDE / max(w, h), math.sqrt(MAX_PIXELS / (w * h)))
    return max(1, round(w * cap)), max(1, round(h * cap))


class LRUBytes:
    def __init__(self, max_bytes):
        self.max, self.size, self._d = max_bytes, 0, OrderedDict()

    def __contains__(self, k): return k in self._d

    def get(self, k):
        if k not in self._d:
            return None
        self._d.move_to_end(k)
        return self._d[k][0]

    def put(self, k, v, nbytes):
        if k in self._d:
            self.size -= self._d.pop(k)[1]
        self._d[k] = (v, nbytes)
        self.size += nbytes
        while self.size > self.max and len(self._d) > 1:      # always keep the newest
            self.size -= self._d.popitem(last=False)[1][1]

    def clear(self):
        self._d.clear(); self.size = 0


def pdf_info(path):
    """(page_count, [(w, h), ...]) - opened and closed on the calling thread."""
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            raise ValueError("password-protected PDFs are not supported")
        if len(doc) == 0:
            raise ValueError("PDF has no pages")
        return len(doc), [(p.rect.width, p.rect.height) for p in doc]
    finally:
        doc.close()


def render_ppm(doc, page_no, w, h):
    page = doc.load_page(page_no)
    r = page.rect                                           # rotation-aware
    pix = page.get_pixmap(matrix=fitz.Matrix(w / r.width, h / r.height), colorspace=fitz.csRGB,
                          alpha=False, annots=True)
    return pix.width, pix.height, pix.tobytes("ppm")        # raw RGB, no compression


class PageRenderer:
    """Renders on ONE background thread (MuPDF documents are not thread-safe) and hands
    results to the UI thread through a queue, so no Tk call is ever made from here."""

    def __init__(self, path):
        self.path = path
        self.results = queue.Queue()
        self._cond, self._jobs, self._epoch, self._run = threading.Condition(), {}, 0, True
        threading.Thread(target=self._loop, daemon=True, name="slidelink-render").start()

    def set_epoch(self, e):
        with self._cond:
            self._epoch = e

    def request(self, page, w, h, priority, epoch, prefetch=False):
        with self._cond:
            self._jobs[(page, w, h)] = (priority, epoch, prefetch)
            self._cond.notify()

    def close(self):
        with self._cond:
            self._run = False
            self._cond.notify()

    def _take(self):
        with self._cond:
            while self._run:
                self._jobs = {k: v for k, v in self._jobs.items() if not v[2] or v[1] == self._epoch}
                if self._jobs:
                    k = min(self._jobs, key=lambda k: self._jobs[k][0])
                    self._jobs.pop(k)
                    return k
                self._cond.wait()

    def _loop(self):
        fitz.TOOLS.set_aa_level(8)                          # maximum anti-aliasing
        try:
            doc = fitz.open(self.path)
        except Exception as e:
            self.results.put((None, None, None, e)); return
        try:
            while True:
                key = self._take()
                if key is None:
                    return
                try:
                    pw, ph, ppm = render_ppm(doc, *key)
                    self.results.put((key, (pw, ph), ppm, None))
                except Exception as e:
                    self.results.put((key, None, None, e))
        finally:
            doc.close()


# ---------------------------------------------------------------- laser pointer
REFERENCE_HEIGHT = 1080.0
SMOOTH_TAU = 0.045                  # seconds; hides the phone's ~25 Hz update rate


def laser_diameter(thickness, view_height):
    """Dot diameter in pixels, proportional to screen height -> same look on 1080p, 4K, projectors."""
    return max(2.0, thickness * view_height / REFERENCE_HEIGHT)


def smooth(cur, target, dt, tau=SMOOTH_TAU):
    return cur + (target - cur) * (1.0 - math.exp(-max(dt, 0.0) / tau))


def png_rgba(w, h, rgba):
    """Minimal PNG encoder (stdlib only). Tk 8.6 loads PNG with a real alpha channel."""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def laser_sprite(diameter):
    """Anti-aliased laser dot (soft glow + solid body + small bright centre) as (size, rgba bytes).
    Edge coverage is computed analytically per pixel, so edges are smooth at any size."""
    r = diameter / 2.0
    glow = max(r + 2.0, diameter * 1.2)
    n = int(math.ceil(glow)) * 2 + 3
    c = (n - 1) / 2.0
    hot = r * 0.2
    out = bytearray(n * n * 4)
    i = 0
    for y in range(n):
        dy = y - c
        for x in range(n):
            d = math.hypot(x - c, dy)
            if d >= glow + 0.5:
                i += 4; continue
            body = min(1.0, max(0.0, r + 0.5 - d))                      # 1 inside, 1px soft edge
            t = max(0.0, 1.0 - (d - r) / (glow - r)) if d > r else 1.0
            ga = 0.45 * t * t                                          # glow falls off smoothly
            a = body + (1.0 - body) * ga
            if a <= 0.0:
                i += 4; continue
            h = min(1.0, max(0.0, hot + 0.5 - d))                       # pale hot centre
            red, grn = 255, int(28 + 110 * h)
            if body < 1.0:
                grn = 28
            out[i:i + 4] = bytes((red, grn, grn, int(255 * a * (0.92 + 0.08 * h))))
            i += 4
    return n, bytes(out)
