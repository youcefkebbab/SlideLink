"""Web remote: a tiny HTTP server so any phone browser (iPhone Safari too) can control the computer
over the local network / Personal Hotspot. No Internet needed."""
import json, secrets, socket, threading, time
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
UI = (Path(__file__).parent / "web_ui.html").read_bytes()


def local_ip():
    """IP address other devices on the same network/hotspot can use (no traffic is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


class WebServer:
    def __init__(self, controller, pins, store, port=PORT, on_event=lambda *a: None):
        self.ctrl, self.pins, self.store, self.port, self.on_event = controller, pins, store, port, on_event
        self.last_seen = 0.0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                b = json.dumps(obj, separators=(",", ":")).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)

            def _authed(self):
                tok = self.headers.get("Authorization", "")[7:]
                ok = bool(tok) and outer.store.get(tok) is not None
                if ok:
                    outer.last_seen = time.time()
                return ok

            def _body(self):
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return {}

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(UI)))
                    self.end_headers()
                    self.wfile.write(UI)
                elif self.path == "/api/state":
                    self._json(outer.ctrl.state()) if self._authed() else self._json({"err": "auth"}, 401)
                elif self.path == "/api/ping":
                    self._json({"ok": True}) if self._authed() else self._json({"err": "auth"}, 401)
                else:
                    self._json({"err": "not_found"}, 404)

            def do_POST(self):
                b = self._body()
                if self.path == "/api/pair":
                    pin = str(b.get("pin", "")).replace(" ", "")
                    if not outer.pins.valid():
                        return self._json({"err": "need_pin"}, 403)
                    if not compare_digest(pin, outer.pins.pin):
                        outer.pins.tries += 1
                        return self._json({"err": "bad_pin"}, 403)
                    tok = secrets.token_urlsafe(24)
                    outer.store.set(tok, "Web phone", b"web")
                    outer.pins.new()
                    outer.last_seen = time.time()
                    outer.on_event("connected", "Phone (browser)")
                    return self._json({"token": tok})
                if not self._authed():
                    return self._json({"err": "auth"}, 401)
                if self.path == "/api/cmd":
                    r = outer.ctrl.handle(b.get("a"), b)
                    return self._json({"ok": r is None, "err": (r or {}).get("code")})
                self._json({"err": "not_found"}, 404)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), H)

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
