"""PDF rendering quality + adjustable laser pointer. Run: python -m pytest tests
(Tk tests need a display; they are skipped automatically on headless machines.)"""
import json, os, sys, tempfile, threading, time, ctypes, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest

fitz = pytest.importorskip("pymupdf")
from slidelink import display
from slidelink.controller import Controller
from slidelink.render import (LRUBytes, PageRenderer, fit_size, laser_diameter, laser_sprite, png_rgba,
                              render_ppm, smooth, pdf_info)
from slidelink.settings import Settings, LASER_DEFAULT, LASER_MAX, LASER_MIN
from slidelink.vlc import Vlc
from test_all import FakeKeys, FakePresenter, make


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("pdf") / "t.pdf")
    doc = fitz.open()
    for i in range(8):
        pg = doc.new_page(width=960, height=540)
        pg.insert_text((60, 120), f"Slide {i + 1}: Sharp text 0123456789", fontsize=40)
        pg.draw_circle((480, 340), 90, color=(0, 0, 1), width=1)
    doc.save(path)
    return path


# ------------------------------------------------------------------ rendering
def test_fit_size_letterbox_and_limits():
    assert fit_size(960, 540, 3840, 2160) == (3840, 2160)
    assert fit_size(960, 540, 1920, 1200) == (1920, 1080)
    assert fit_size(540, 960, 1920, 1080) == (608, 1080)
    w, h = fit_size(100, 100, 10**5, 10**5)
    assert w * h <= 120_000_000 * 1.001 and max(w, h) <= 16384


def test_render_is_exact_size_raw_and_antialiased(pdf):
    doc = fitz.open(pdf)
    fitz.TOOLS.set_aa_level(8)
    for size in [(1280, 720), (1920, 1080), (3840, 2160), (7680, 4320)]:
        w, h, ppm = render_ppm(doc, 0, *size)
        assert (w, h) == size                                  # rendered AT the size, not scaled to it
        assert ppm.startswith(b"P6")                           # raw uncompressed RGB (no JPEG/PNG)
    w, h, ppm = render_ppm(doc, 0, 3840, 2160)
    px = ppm[len(ppm) - w * h * 3:]
    assert len({px[i] for i in range(0, len(px), 3 * 97)}) > 20    # many grey levels = smooth edges
    assert min(px[::3]) < 40                                        # real dark text ink
    doc.close()


def test_thin_stroke_stays_thin_at_high_resolution(pdf):
    """A 1pt circle must stay ~1 device px per page-point (re-rasterised), not turn into a blurry blob."""
    doc = fitz.open(pdf)
    def ink(width):
        w, h, ppm = render_ppm(doc, 0, width, width * 9 // 16)
        px = ppm[len(ppm) - w * h * 3:]
        row = h * 340 // 540
        return sum(1 for v in px[row * w * 3: (row + 1) * w * 3: 3] if v < 235)
    assert ink(7680) <= ink(960) * 10                          # grows roughly with scale (8x), no extra smear
    doc.close()


def test_pdf_info_and_errors(pdf, tmp_path):
    n, sizes = pdf_info(pdf)
    assert n == 8 and sizes[0] == (960, 540)
    bad = tmp_path / "bad.pdf"; bad.write_bytes(b"not a pdf")
    with pytest.raises(Exception):
        pdf_info(str(bad))


def test_lru_cache_budget():
    c = LRUBytes(100)
    c.put("a", 1, 60); c.put("b", 2, 60)
    assert "a" not in c and c.get("b") == 2
    c.put("big", 3, 500)
    assert "big" in c


def test_worker_priority_and_stale_prefetch_dropped(pdf):
    r = PageRenderer(pdf)
    r.set_epoch(5)
    r.request(3, 800, 450, 2, 4, prefetch=True)               # stale epoch -> skipped
    r.request(1, 800, 450, 0, 5)
    key, size, ppm, err = r.results.get(timeout=5)
    assert key == (1, 800, 450) and size == (800, 450) and err is None
    time.sleep(0.3)
    assert r.results.empty()
    r.close()


# ---------------------------------------------------------------------- laser
def test_laser_thickness_is_resolution_independent():
    assert laser_diameter(14, 1080) == 14 and laser_diameter(14, 2160) == 28 and laser_diameter(14, 540) == 7
    assert laser_diameter(1, 100) >= 2


def test_laser_smoothing_converges_and_is_framerate_independent():
    a = b = 0.0
    for _ in range(60): a = smooth(a, 1.0, 1 / 60)
    for _ in range(240): b = smooth(b, 1.0, 1 / 240)
    assert abs(a - b) < 1e-9 and a > 0.99


@pytest.mark.parametrize("d", [4, 14, 33, 60, 120])
def test_laser_sprite_is_antialiased_and_valid_png(d):
    n, rgba = laser_sprite(d)
    c = n // 2
    centre = rgba[(c * n + c) * 4:(c * n + c) * 4 + 4]
    assert centre[0] == 255 and centre[3] > 230                  # opaque red body
    alphas = {rgba[(c * n + x) * 4 + 3] for x in range(c, n)}
    assert len(alphas) > 3 and 0 in alphas                       # smooth fall-off to fully transparent
    assert rgba[3] == 0 and rgba[-1] == 0                        # corners transparent
    pix = fitz.Pixmap(png_rgba(n, n, rgba))                      # decodes as a real PNG with alpha
    assert (pix.width, pix.height, pix.alpha) == (n, n, 1)


def test_laser_sprite_gets_bigger_with_thickness():
    def area(d):
        rgba = laser_sprite(d)[1]
        return sum(1 for i in range(3, len(rgba), 4) if rgba[i] > 200)
    assert area(40) > area(10) * 5


def test_settings_persist_clamp_and_survive_garbage(tmp_path):
    f = tmp_path / "s.json"
    s = Settings(f); s.laser_size, s.laser_enabled = 33, False; s.save()
    t = Settings(f); assert (t.laser_size, t.laser_enabled) == (33, False)
    f.write_text('{"laser_size": 9999}'); assert Settings(f).laser_size == LASER_MAX
    f.write_text('{"laser_size": -5}'); assert Settings(f).laser_size == LASER_MIN
    f.write_text("garbage"); assert Settings(f).laser_size == LASER_DEFAULT


# ----------------------------------------------------------------- controller
def test_controller_laser_commands_and_state():
    pres, keys = FakePresenter(), FakeKeys()
    ctrl = Controller(pres, Vlc(port=1), keys)
    calls = []
    pres.set_laser_size = lambda v: calls.append(("size", v))
    pres.reset_laser_size = lambda: calls.append(("reset",))
    pres.set_laser_enabled = lambda on: calls.append(("enable", on))
    assert ctrl.handle("laser_size", {"v": 40}) is None
    assert ctrl.handle("laser_size", {"v": "22.4"}) is None
    assert ctrl.handle("laser_reset", {}) is None
    assert ctrl.handle("laser_enable", {"on": False}) is None
    assert calls == [("size", 40.0), ("size", 22.4), ("reset",), ("enable", False)]
    for bad in ({}, {"v": "abc"}, {"v": None}, {"v": float("nan")}):
        assert ctrl.handle("laser_size", bad)["code"] == "bad_param"
    pres.s = {"open": True, "page": 3, "pages": 9, "screen": "", "fs": False, "laser_size": 25, "laser_enabled": False}
    assert ctrl.state() == {"mode": "pdf", "pg": 3, "n": 9, "scr": "", "fs": False, "ls": 25, "le": False}


def test_laser_size_over_browser_remote_http(tmp_path):
    from slidelink.web import WebServer
    pres, keys, vlc, ctrl, pins, store, _ = make(str(tmp_path))
    got = []
    pres.set_laser_size = lambda v: got.append(v)
    ws = WebServer(ctrl, pins, store, port=0); ws.start(); port = ws.httpd.server_port
    def call(path, body=None, tok=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {tok}"} if tok else {})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
    assert call("/api/cmd", {"a": "laser_size", "v": 30})[0] == 401          # still needs pairing
    tok = call("/api/pair", {"pin": pins.pin})[1]["token"]
    assert call("/api/cmd", {"a": "laser_size", "v": 30}, tok)[1]["ok"] is True
    assert call("/api/cmd", {"a": "laser_size", "v": "x"}, tok)[1]["err"] == "bad_param"
    assert got == [30.0]
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
    assert 'id="ls"' in html and "laser_size" in html and "laser_reset" in html
    ws.stop()


# ------------------------------------------------------------------ high DPI
def test_dpi_awareness_fallback_order(monkeypatch):
    calls = []
    class F:  # fake windll
        class user32:
            @staticmethod
            def SetProcessDpiAwarenessContext(x): calls.append("v2"); return 0
            @staticmethod
            def SetProcessDPIAware(): calls.append("system"); return 1
        class shcore:
            @staticmethod
            def SetProcessDpiAwareness(x): calls.append("shcore"); return 0
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", F, raising=False)
    assert display.enable_high_dpi() == "per-monitor"            # v2 refused -> per-monitor
    F.user32.SetProcessDpiAwarenessContext = staticmethod(lambda x: 1)
    assert display.enable_high_dpi() == "per-monitor-v2"
    monkeypatch.setattr(sys, "platform", "linux")
    assert display.enable_high_dpi() == "not-windows"


# ------------------------------------------------- real Tk presenter (needs display)
tk = pytest.importorskip("tkinter")
needs_display = pytest.mark.skipif(sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
                                   reason="no display (run under xvfb-run)")


def pump(root, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.004)
    return False


@pytest.fixture
def presenter(pdf, tmp_path):
    from slidelink.presenter import Presenter
    root = tk.Tk(); root.withdraw()
    p = Presenter(root, Settings(tmp_path / "settings.json"))
    p.open(pdf); p.win.geometry("1600x900+0+0")
    assert pump(root, lambda: p._img is not None and p._img.width() == 1600)
    yield root, p
    p.close(); root.destroy()


@needs_display
def test_presenter_renders_exact_canvas_size_and_prefetches(presenter):
    root, p = presenter
    assert (p._img.width(), p._img.height()) == (1600, 900)
    assert p.snapshot()["pages"] == 8
    assert pump(root, lambda: all((i, 1600, 900) in p.cache for i in (1, 2, 3)))
    p._go(1); root.update()
    assert p._img.width() == 1600 and p.snapshot()["page"] == 2     # cached page appears immediately, full-res


@needs_display
def test_presenter_rerenders_at_new_exact_size_on_resize(presenter):
    root, p = presenter
    p.win.geometry("1000x600+0+0")
    expected = fit_size(960, 540, 1000, 600)
    assert pump(root, lambda: p._img is not None and (p._img.width(), p._img.height()) == expected)


@needs_display
def test_previous_sharp_slide_stays_until_new_one_is_ready(presenter):
    root, p = presenter
    before = p._img
    p._go(7)                                    # not cached yet
    assert p._img is before                     # no blurry placeholder was swapped in
    assert pump(root, lambda: p._img is not before and p._img.width() == 1600)


@needs_display
def test_laser_panel_slider_preview_reset_and_persistence(presenter, tmp_path):
    root, p = presenter
    p.laser(0.25, 0.5, True); pump(root, lambda: False, 0.4)
    p._show_panel(); root.update()
    panel = p.panel
    assert "Thickness: 14" in panel.value.cget("text")
    panel.scale.set(55); pump(root, lambda: p.settings.laser_size == 55)          # live, no apply button
    assert "55" in panel.value.cget("text")
    assert p._lz_img.width() > laser_sprite(laser_diameter(14, 900))[0]              # dot on screen got bigger
    assert json.loads((tmp_path / "settings.json").read_text())["laser_size"] == 55  # saved
    p.set_laser_size(22); pump(root, lambda: panel.scale.get() == 22)               # phone change reaches panel
    panel.win.nametowidget(panel.win.winfo_children()[-1]).invoke()                  # Reset button
    pump(root, lambda: p.settings.laser_size == LASER_DEFAULT)
    assert panel.scale.get() == LASER_DEFAULT
    assert Settings(tmp_path / "settings.json").laser_size == LASER_DEFAULT


@needs_display
def test_laser_position_scaling_hiding_and_disable(presenter):
    root, p = presenter
    p.laser(0.25, 0.5, True); pump(root, lambda: False, 0.4)
    x, y = p.canvas.coords(p._lz_item)
    assert abs(x - 400) < 1.5 and abs(y - 450) < 1.5                  # normalised -> pixel, accurate
    p.laser(0, 0, False); pump(root, lambda: False, 0.1)
    assert p.canvas.itemcget(p._lz_item, "state") == "hidden"
    p.laser(0.5, 0.5, True); pump(root, lambda: False, 0.2)
    p.black(); pump(root, lambda: False, 0.2)
    assert p.canvas.itemcget(p._lz_item, "state") == "hidden"         # no laser on a black screen
    p.black(); p.set_laser_enabled(False); pump(root, lambda: False, 0.2)
    p.laser(0.5, 0.5, True); pump(root, lambda: False, 0.2)
    assert p.canvas.itemcget(p._lz_item, "state") == "hidden"         # disabled -> phone cannot show it
    assert p.snapshot()["laser_enabled"] is False


@needs_display
def test_controller_drives_real_presenter(presenter):
    root, p = presenter
    ctrl = Controller(p, Vlc(port=1), FakeKeys())
    assert ctrl.handle("laser_size", {"v": 48}) is None
    assert pump(root, lambda: p.settings.laser_size == 48)
    assert ctrl.state()["ls"] == 48 and ctrl.state()["mode"] == "pdf"
    ctrl.handle("laser_reset", {}); assert pump(root, lambda: p.settings.laser_size == LASER_DEFAULT)
    ctrl.handle("laser_size", {"v": 9999}); assert pump(root, lambda: p.settings.laser_size == LASER_MAX)  # clamped
