import json, os, sys, threading, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from slidelink.protocol import *
from slidelink.session import PinManager, PairStore, Session
from slidelink.controller import Controller
from slidelink.vlc import Vlc


class FakePresenter:
    def __init__(s): s.s = {"open": True, "page": 1, "pages": 10, "screen": "", "fs": False}; s.log = []
    def snapshot(s): return s.s
    def goto(s, n): s.s["page"] = n
    def __getattr__(s, name): return lambda *a: s.log.append(name)


class FakeKeys:
    def __init__(s): s.log = []
    def press(s, k): s.log.append(k)


class FakeVlcHandler(BaseHTTPRequestHandler):
    calls = []
    state = {"state": "playing", "time": 12, "length": 100, "volume": 256, "fullscreen": False}
    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        assert self.headers["Authorization"].startswith("Basic ")
        if q: FakeVlcHandler.calls.append(q)
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(self.state).encode())
    def log_message(self, *a): pass


def phone_hello(pin_or_secret, is_pin, did="phone1"):
    priv = X25519PrivateKey.generate()
    pk = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    secret = pin_key(pin_or_secret) if is_pin else pin_or_secret
    msg = {"t": "hello", "id": did, "name": "Test Phone", "pk": b64(pk), "auth": b64(mac(secret, b"C", pk))}
    return priv, pk, secret, json.dumps(msg).encode()


def phone_finish(priv, pk, secret, reply):
    r = json.loads(reply)
    pk_s = unb64(r["pk"])
    assert hmac_ok(r["auth"], mac(secret, b"S", pk_s, pk))
    shared = priv.exchange(X25519PublicKey.from_public_bytes(pk_s))
    c2s, s2c = derive_keys(shared, secret, pk, pk_s)
    return Channel(send_key=c2s, recv_key=s2c)


def hmac_ok(a, b): import hmac; return hmac.compare_digest(unb64(a), b)


def make(tmp):
    pres, keys = FakePresenter(), FakeKeys()
    srv = HTTPServer(("127.0.0.1", 0), FakeVlcHandler); threading.Thread(target=srv.serve_forever, daemon=True).start()
    vlc = Vlc(port=srv.server_port)
    ctrl = Controller(pres, vlc, keys)
    pins, store = PinManager(), PairStore(os.path.join(tmp, "p.json"))
    return pres, keys, vlc, ctrl, pins, store, Session(store, pins, ctrl.handle)


def test_framing():
    data = os.urandom(450)
    r = Reassembler(); out = [r.feed(f) for f in frames(data)]
    assert out[-1] == data and all(o is None for o in out[:-1])
    assert all(len(f) <= CHUNK + 1 for f in frames(data))


def test_pair_then_reconnect_and_commands():
    with tempfile.TemporaryDirectory() as tmp:
        pres, keys, vlc, ctrl, pins, store, sess = make(tmp)
        priv, pk, secret, hello = phone_hello(pins.pin, True)
        out = sess.handle(hello)
        ch = phone_finish(priv, pk, secret, out[0])
        paired = ch.open(out[1]); assert paired["t"] == "paired"
        new_secret = unb64(paired["secret"])
        # commands
        assert sess.handle(ch.seal({"t": "cmd", "a": "next"})) == []
        assert pres.log == ["next"]
        sess.handle(ch.seal({"t": "cmd", "a": "goto", "n": 7})); assert pres.s["page"] == 7
        # ping
        pong = ch.open(sess.handle(ch.seal({"t": "ping", "id": 5}))[0]); assert pong["t"] == "pong" and pong["id"] == 5
        # video
        sess.handle(ch.seal({"t": "cmd", "a": "fwd10"}))
        assert {"command": "seek", "val": "+10S"} in FakeVlcHandler.calls
        sess.handle(ch.seal({"t": "cmd", "a": "volup"}))
        assert any(c.get("command") == "volume" and c["val"] == "282" for c in FakeVlcHandler.calls)
        st = ctrl.state(); assert st["mode"] == "video" and st["vl"] == 100 and st["vv"] == 100
        # replay rejected
        raw = ch.seal({"t": "cmd", "a": "prev"}); sess.handle(raw)
        assert json.loads(sess.handle(raw)[0])["code"] == "reauth"
        # reconnect with stored secret (PIN no longer needed)
        pins.expires = 0
        sess2 = Session(PairStore(os.path.join(tmp, "p.json")), pins, ctrl.handle)
        priv, pk, sec, hello = phone_hello(new_secret, False)
        out = sess2.handle(hello); assert len(out) == 1
        ch2 = phone_finish(priv, pk, sec, out[0])
        assert sess2.handle(ch2.seal({"t": "ping", "id": 1}))


def test_wrong_pin_and_lockout():
    with tempfile.TemporaryDirectory() as tmp:
        *_, pins, store, sess = make(tmp)
        for _ in range(5):
            assert json.loads(sess.handle(phone_hello("000000" if pins.pin != "000000" else "111111", True)[3])[0])["code"] == "bad_pin"
        assert not pins.valid()
        assert json.loads(sess.handle(phone_hello(pins.pin, True)[3])[0])["code"] == "need_pin"


def test_pdf_external_keys_and_state():
    with tempfile.TemporaryDirectory() as tmp:
        pres, keys, vlc, ctrl, *_ = make(tmp)
        pres.s = {"open": False}
        FakeVlcHandler.state = {"state": "stopped"}
        ctrl.handle("next", {}); ctrl.handle("first", {}); ctrl.handle("start", {})
        assert keys.log == ["right", "home", "f5"]
        assert ctrl.state()["mode"] == "none"
        pres.s = {"open": True, "page": 3, "pages": 9, "screen": "b", "fs": True}
        assert ctrl.state() == {"mode": "pdf", "pg": 3, "n": 9, "scr": "b", "fs": True}


def test_vlc_missing():
    v = Vlc(port=1)
    ctrl = Controller(FakePresenter(), v, FakeKeys())
    assert ctrl.handle("play", {})["code"] == "no_vlc"


def test_web_remote():
    import urllib.request, urllib.error
    from slidelink.web import WebServer, UI
    with tempfile.TemporaryDirectory() as tmp:
        pres, keys, vlc, ctrl, pins, store, _ = make(tmp)
        FakeVlcHandler.state = {"state": "paused", "time": 5, "length": 50, "volume": 128, "fullscreen": False}
        ws = WebServer(ctrl, pins, store, port=0); ws.start(); port = ws.httpd.server_port
        def call(path, body=None, tok=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {tok}"} if tok else {})
            try:
                with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r: assert b"SlideLink" in r.read() and r.status == 200
        assert call("/api/state")[0] == 401 and call("/api/cmd", {"a": "next"})[0] == 401
        assert call("/api/pair", {"pin": "xxxxxx"})[1]["err"] == "bad_pin"
        pin = pins.pin
        code, r = call("/api/pair", {"pin": pin}); tok = r["token"]
        assert code == 200 and pins.pin != pin
        assert call("/api/state", tok=tok)[1]["mode"] == "video"
        pres.s = {"open": False}; FakeVlcHandler.state = {"state": "stopped"}
        call("/api/cmd", {"a": "next"}, tok); assert keys.log[-1] == "right"
        assert call("/api/cmd", {"a": "play"}, tok)[1]["ok"] is True
        pres.s = {"open": True, "page": 2, "pages": 5, "screen": "", "fs": False}
        assert call("/api/state", tok=tok)[1] == {"mode": "pdf", "pg": 2, "n": 5, "scr": "", "fs": False}
        # token survives restart
        assert PairStore(os.path.join(tmp, "p.json")).get(tok) is not None
        for _ in range(5): call("/api/pair", {"pin": "xxxxxx"})
        assert call("/api/pair", {"pin": pins.pin})[1]["err"] == "need_pin"
        ws.stop()
