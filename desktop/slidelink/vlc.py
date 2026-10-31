"""VLC control through its local-only HTTP interface (127.0.0.1)."""
import base64, json, os, shutil, subprocess, urllib.parse, urllib.request

PORT, PASSWORD = 8080, "slidelink"


def find_vlc():
    p = shutil.which("vlc")
    if p:
        return p
    for c in (r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"):
        if os.path.exists(c):
            return c
    return None


class Vlc:
    def __init__(self, port=PORT, password=PASSWORD):
        self.base = f"http://127.0.0.1:{port}/requests/status.json"
        self.port, self.password = port, password
        self._auth = "Basic " + base64.b64encode(f":{password}".encode()).decode()
        self._premute = 100

    def _get(self, params=None):
        url = self.base + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": self._auth})
        with urllib.request.urlopen(req, timeout=0.8) as r:
            return json.loads(r.read())

    def status(self):
        try:
            return self._get()
        except Exception:
            return None

    def command(self, cmd, **kw):
        try:
            self._get({"command": cmd, **kw})
            return True
        except Exception:
            return False

    def volume_pct(self, st=None):
        st = st or self.status() or {}
        return round(st.get("volume", 256) * 100 / 256)

    def set_volume_pct(self, pct):
        return self.command("volume", val=str(round(max(0, min(125, pct)) * 256 / 100)))

    def toggle_mute(self):
        cur = self.volume_pct()
        if cur > 0:
            self._premute = cur
            return self.set_volume_pct(0)
        return self.set_volume_pct(self._premute or 100)

    def launch(self, path=None):
        exe = find_vlc()
        if not exe:
            return False
        args = [exe, "--extraintf=http", "--http-host=127.0.0.1", f"--http-port={self.port}",
                f"--http-password={self.password}"] + ([path] if path else [])
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
