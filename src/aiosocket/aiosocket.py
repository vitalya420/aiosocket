import asyncio
import socket
from typing import Optional

from aiosocket.exceptions import NotAllowedError
from aiosocket.utils import wait_sock_ready_to_write, wait_sock_ready_to_read


class AsyncSocket(socket.socket):
    """
    Making socket.socket async!
    Uses loop.add_reader() and loop.add_writer() when it's ready to do IO operation.
    """

    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
        super().__init__(family, type, proto, fileno)
        super().setblocking(False)
        self._async_timeout: Optional[float] = None
        self._loop = asyncio.get_event_loop()

    async def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, address, /):
        """Connect but async. Uses connect_ex() under the hood and monitors fd to ready to write"""
        super().connect_ex(address)
        await self.wait_until_writeable()

    async def send(self, data, flags=0, /):
        total_sent = 0
        need_to_send = len(data)

        while total_sent < need_to_send:
            try:
                total_sent += super().send(data, flags)
            except BlockingIOError:
                await self.wait_until_writeable()
        return total_sent

    async def recv(self, bufsize, flags=0, /):
        if self._async_timeout is not None:
            try:
                return await asyncio.wait_for(
                    self._recv(bufsize, flags), self._async_timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Timeout reading response")
        else:
            return await self._recv(bufsize, flags)

    async def _recv(self, bufsize, flags=0, /):
        total_received = 0
        data = b""
        while total_received < bufsize:
            try:
                chunk = super().recv(bufsize - total_received, flags)
                if not chunk:
                    break
                total_received += len(chunk)
                data += chunk
            except BlockingIOError:
                await self.wait_until_readable()
        return data

    def settimeout(self, value, /):
        """Implemented own async timeout"""
        self._async_timeout = value

    def setblocking(self, flag, /):
        if flag:
            raise NotAllowedError(
                "Blocking async socket will make it just a regular socket"
            )

    async def wait_until_writeable(self, /):
        return await wait_sock_ready_to_write(self.fileno())

    async def wait_until_readable(self, /):
        return await wait_sock_ready_to_read(self.fileno())
