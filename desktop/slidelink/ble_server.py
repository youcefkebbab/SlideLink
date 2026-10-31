"""BLE GATT peripheral (via `bless`: BlueZ on Linux, WinRT on Windows)."""
import asyncio
from .protocol import SERVICE_UUID, RX_UUID, TX_UUID, Reassembler, frames


class BleServer:
    def __init__(self, name, session, controller, on_status):
        self.name, self.session, self.controller, self.on_status = name, session, controller, on_status
        self.reasm, self.server = Reassembler(), None

    async def run(self):
        from bless import BlessServer, GATTCharacteristicProperties as P, GATTAttributePermissions as A
        self.loop = asyncio.get_running_loop()
        self.q, self._send_lock = asyncio.Queue(), asyncio.Lock()
        self.server = BlessServer(name=self.name, loop=self.loop)
        self.server.write_request_func = self._on_write
        self.server.read_request_func = lambda c, **k: c.value
        await self.server.add_new_service(SERVICE_UUID)
        await self.server.add_new_characteristic(
            SERVICE_UUID, RX_UUID, P.write | P.write_without_response, None, A.writeable)
        await self.server.add_new_characteristic(
            SERVICE_UUID, TX_UUID, P.read | P.notify, bytearray(b"\x01"), A.readable)
        await self.server.start()
        self.on_status("advertising", self.name)
        await asyncio.gather(self._worker(), self._state_loop())

    def _on_write(self, characteristic, value, **kw):
        characteristic.value = value
        self.loop.call_soon_threadsafe(self.q.put_nowait, bytes(value))

    async def _worker(self):
        while True:
            raw = self.reasm.feed(await self.q.get())
            if raw is None:
                continue
            outs = await self.loop.run_in_executor(None, self.session.handle, raw)
            for o in outs:
                await self._send(o)
            if self.session.authenticated:
                await asyncio.sleep(0.15)
                await self._push_state()

    async def _state_loop(self):
        while True:
            await asyncio.sleep(1)
            if self.session.authenticated:
                await self._push_state()

    async def _push_state(self):
        st = await self.loop.run_in_executor(None, self.controller.state)
        if self.session.authenticated:
            await self._send(self.session.seal({"t": "state", **st}))

    async def _send(self, data: bytes):
        async with self._send_lock:
            ch = self.server.get_characteristic(TX_UUID)
            for f in frames(data):
                ch.value = bytearray(f)
                self.server.update_value(SERVICE_UUID, TX_UUID)
                await asyncio.sleep(0.02)
