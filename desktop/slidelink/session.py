"""Pairing handshake, paired-device store and command dispatch (transport independent)."""
import json, os, secrets, time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from hmac import compare_digest
from .protocol import Channel, ENC, b64, unb64, derive_keys, mac, pin_key


class PinManager:
    TTL, MAX_TRIES = 300, 5

    def __init__(self):
        self.new()

    def new(self):
        self.pin = f"{secrets.randbelow(10**6):06d}"
        self.expires = time.time() + self.TTL
        self.tries = 0

    def valid(self):
        return time.time() < self.expires and self.tries < self.MAX_TRIES


class PairStore:
    def __init__(self, path=None):
        base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
        self.path = Path(path) if path else base / "slidelink" / "paired.json"
        self.data = {}
        try:
            self.data = json.loads(self.path.read_text())
        except Exception:
            pass

    def get(self, did):
        e = self.data.get(did)
        return unb64(e["secret"]) if e else None

    def set(self, did, name, secret):
        self.data[did] = {"name": name, "secret": b64(secret)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


class Session:
    def __init__(self, store, pins, handler, on_event=lambda *a: None):
        self.store, self.pins, self.handler, self.on_event = store, pins, handler, on_event
        self.chan = None

    @property
    def authenticated(self):
        return self.chan is not None

    def reset(self):
        self.chan = None

    @staticmethod
    def _plain(msg):
        return json.dumps(msg, separators=(",", ":")).encode()

    def seal(self, msg):
        return self.chan.seal(msg)

    def handle(self, raw: bytes):
        """Process one complete incoming message; return list of messages to send back."""
        try:
            if raw[0] == ENC:
                if not self.chan:
                    return [self._plain({"t": "err", "code": "reauth"})]
                return self._encrypted(self.chan.open(raw))
            msg = json.loads(raw)
            if msg.get("t") == "hello":
                return self._hello(msg)
        except Exception:
            self.chan = None
            return [self._plain({"t": "err", "code": "reauth"})]
        return []

    def _encrypted(self, m):
        t = m.get("t")
        if t == "ping":
            return [self.seal({"t": "pong", "id": m.get("id")})]
        if t == "cmd":
            r = self.handler(m.get("a"), m)
            return [self.seal(r)] if r else []
        if t == "bye":
            self.reset()
        return []

    def _hello(self, m):
        did, pk_c, auth = m["id"], unb64(m["pk"]), unb64(m["auth"])
        cands = []
        if (s := self.store.get(did)) is not None:
            cands.append((s, True))
        if self.pins.valid():
            cands.append((pin_key(self.pins.pin), False))
        if not cands:
            return [self._plain({"t": "err", "code": "need_pin"})]
        match = next(((s, p) for s, p in cands if compare_digest(auth, mac(s, b"C", pk_c))), None)
        if not match:
            if self.pins.valid():
                self.pins.tries += 1
            return [self._plain({"t": "err", "code": "bad_pin"})]
        secret, was_paired = match
        priv = X25519PrivateKey.generate()
        pk_s = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        shared = priv.exchange(X25519PublicKey.from_public_bytes(pk_c))
        k_c2s, k_s2c = derive_keys(shared, secret, pk_c, pk_s)
        self.chan = Channel(send_key=k_s2c, recv_key=k_c2s)
        out = [self._plain({"t": "hello", "pk": b64(pk_s), "auth": b64(mac(secret, b"S", pk_s, pk_c))})]
        name = m.get("name", "Phone")
        if not was_paired:
            new_secret = os.urandom(32)
            self.store.set(did, name, new_secret)
            self.pins.new()
            out.append(self.seal({"t": "paired", "secret": b64(new_secret)}))
        self.on_event("connected", name)
        return out
