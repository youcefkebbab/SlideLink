"""Executes phone commands: built-in PDF presenter, external-viewer keystrokes, VLC."""
PDF_ACTIONS = {"next", "prev", "first", "last", "goto", "start", "exit", "fullscreen", "black", "white", "laser"}
VIDEO_ACTIONS = {"play", "pause", "toggle", "stop", "back10", "fwd10", "vprev", "vnext",
                 "volup", "voldown", "mute", "vfull", "seek"}
# keystrokes used for external viewers (PowerPoint, Okular, Evince, Adobe, browser...)
EXT_KEYS = {"next": "right", "prev": "left", "first": "home", "last": "end", "start": "f5",
            "exit": "esc", "fullscreen": "f11", "black": "b", "white": "w"}


class Keys:
    def __init__(self):
        self._kb = None

    def press(self, name):
        from pynput.keyboard import Controller, Key
        self._kb = self._kb or Controller()
        k = {"right": Key.right, "left": Key.left, "home": Key.home, "end": Key.end, "f5": Key.f5,
             "esc": Key.esc, "f11": Key.f11}.get(name, name)
        self._kb.press(k)
        self._kb.release(k)


class Controller:
    def __init__(self, presenter, vlc, keys=None):
        self.presenter, self.vlc, self.keys = presenter, vlc, keys or Keys()

    def handle(self, action, msg):
        if action in PDF_ACTIONS:
            return self._pdf(action, msg)
        if action in VIDEO_ACTIONS:
            return self._video(action, msg)
        return {"t": "err", "code": "unknown_action"}

    def _pdf(self, a, m):
        p = self.presenter
        if p.snapshot().get("open"):
            if a == "goto":
                p.goto(int(m.get("n", 1)))
            elif a == "laser":
                p.laser(float(m.get("x", 0)), float(m.get("y", 0)), bool(m.get("on", True)))
            else:
                getattr(p, a)()
            return None
        if a in EXT_KEYS:
            try:
                self.keys.press(EXT_KEYS[a])
            except Exception:
                return {"t": "err", "code": "keys_failed"}
            return None
        return {"t": "err", "code": "no_pdf"}

    def _video(self, a, m):
        v = self.vlc
        if v.status() is None:
            return {"t": "err", "code": "no_vlc"}
        table = {
            "play": lambda: v.command("pl_forceresume"), "pause": lambda: v.command("pl_forcepause"),
            "toggle": lambda: v.command("pl_pause"), "stop": lambda: v.command("pl_stop"),
            "back10": lambda: v.command("seek", val="-10S"), "fwd10": lambda: v.command("seek", val="+10S"),
            "vprev": lambda: v.command("pl_previous"), "vnext": lambda: v.command("pl_next"),
            "volup": lambda: v.set_volume_pct(v.volume_pct() + 10),
            "voldown": lambda: v.set_volume_pct(v.volume_pct() - 10),
            "mute": v.toggle_mute, "vfull": lambda: v.command("fullscreen"),
            "seek": lambda: v.command("seek", val=f"{max(0, min(100, float(m.get('pct', 0)))):.1f}%"),
        }
        table[a]()
        return None

    def state(self):
        """Compact snapshot for the phone (also decides which remote UI it shows)."""
        st = self.vlc.status()
        if st and st.get("state") in ("playing", "paused"):
            return {"mode": "video", "vs": st["state"], "vt": st.get("time", 0), "vl": st.get("length", 0),
                    "vv": self.vlc.volume_pct(st), "vf": bool(st.get("fullscreen"))}
        snap = self.presenter.snapshot()
        if snap.get("open"):
            return {"mode": "pdf", "pg": snap["page"], "n": snap["pages"], "scr": snap["screen"], "fs": snap["fs"]}
        return {"mode": "none"}
