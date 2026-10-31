"""SlideLink wire protocol: GATT UUIDs, framing, key derivation, AES-GCM channel."""
import base64, hashlib, hmac, json, os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SERVICE_UUID = "7d1c0001-5a1d-4e0b-9c3a-51d3e11a0001"
RX_UUID = "7d1c0002-5a1d-4e0b-9c3a-51d3e11a0001"  # phone -> desktop (write)
TX_UUID = "7d1c0003-5a1d-4e0b-9c3a-51d3e11a0001"  # desktop -> phone (notify)
CHUNK = 100          # payload bytes per BLE packet (+1 header byte); needs MTU >= 104
ENC = 0x01           # first byte of an encrypted message (plain messages start with '{')

b64 = lambda b: base64.b64encode(b).decode()
unb64 = base64.b64decode


def frames(data: bytes):
    """Split a message into BLE-sized chunks. Header byte: 0 = more follows, 1 = last."""
    out = []
    for i in range(0, len(data), CHUNK):
        out.append(bytes([1 if i + CHUNK >= len(data) else 0]) + data[i:i + CHUNK])
    return out or [b"\x01"]


class Reassembler:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, chunk: bytes):
        if not chunk:
            return None
        self.buf += chunk[1:]
        if chunk[0] == 1:
            data = bytes(self.buf)
            self.buf.clear()
            return data
        if len(self.buf) > 8192:
            self.buf.clear()
        return None


def pin_key(pin: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), b"slidelink-pin-v1", 100_000, 32)


def mac(secret: bytes, label: bytes, *parts: bytes) -> bytes:
    return hmac.new(secret, label + b"".join(parts), hashlib.sha256).digest()


def derive_keys(shared: bytes, secret: bytes, pk_c: bytes, pk_s: bytes):
    """Returns (client->server key, server->client key)."""
    okm = HKDF(hashes.SHA256(), 64, pk_c + pk_s, b"slidelink-v1").derive(shared + secret)
    return okm[:32], okm[32:]


class Channel:
    """Authenticated-encryption channel with replay protection."""

    def __init__(self, send_key: bytes, recv_key: bytes):
        self._s, self._r = AESGCM(send_key), AESGCM(recv_key)
        self.seq, self.last_in = 0, 0

    def seal(self, msg: dict) -> bytes:
        self.seq += 1
        body = json.dumps(dict(msg, q=self.seq), separators=(",", ":")).encode()
        nonce = os.urandom(12)
        return bytes([ENC]) + nonce + self._s.encrypt(nonce, body, b"SL1")

    def open(self, raw: bytes) -> dict:
        msg = json.loads(self._r.decrypt(raw[1:13], raw[13:], b"SL1"))
        if msg.get("q", 0) <= self.last_in:
            raise ValueError("replayed message")
        self.last_in = msg["q"]
        return msg
