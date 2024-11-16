import asyncio
import socket
from typing import Optional, Tuple

from aiosocket.exceptions import NotAllowedError
from aiosocket.utils import (
    wait_sock_ready_to_write,
    wait_sock_ready_to_read,
)
from aiosocket.socks5.messages import (
    Hello,
    HelloResponse,
    UsernamePassword,
    AuthenticationResponse,
    Request,
    Reply,
)
from aiosocket.socks5.enums import Method, SocksVersion, Command, ATYP
from aiosocket.socks5.exceptions import (
    NoAcceptableMethods,
    AuthenticationError,
    ProxyConnectionError,
)


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
        self.is_connected_to_proxy: bool = False

    async def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def socks5_connect(
        self, addr: Tuple[str, int], credentials: Optional[Tuple[str, str]] = None
    ):
        if self.type == socket.SOCK_DGRAM:
            raise NotImplementedError("Socks5 proxy via udp not implemented yet")
        try:
            await self.connect(addr)
            method = (
                Method.USERNAME_PASSWORD
                if credentials is not None
                else Method.NO_AUTHENTICATION_REQUIRED
            )
            hello = Hello(ver=SocksVersion.SOCKS5, methods=[method]).to_bytes()
            await self.send(hello)
            response_bytes = await self.recv(2)
            response = HelloResponse.from_bytes(response_bytes)

            if response.method == Method.NO_ACCEPTABLE_METHODS:
                raise NoAcceptableMethods(
                    "No acceptable methods are available. Have you forgot to provide your credentials?"
                )

            if response.method == Method.USERNAME_PASSWORD and credentials is not None:
                username, password = credentials
                auth_message = UsernamePassword(
                    SocksVersion.SOCKS5, username=username, password=password
                )
                await self.send(auth_message.to_bytes())
                response_bytes = await self.recv(2)
                if not AuthenticationResponse.from_bytes(response_bytes).is_ok():
                    raise AuthenticationError("Authentication failed")
            self.is_connected_to_proxy = True
        except ConnectionRefusedError:
            raise ProxyConnectionError(f"Connection to proxy {addr} refused")

    async def connect(self, address, /):
        """Connect but async. Uses connect_ex() under the hood and monitors fd to ready to write"""
        if self.is_connected_to_proxy:
            return await self._do_proxy_connect(address)
        super().connect_ex(address)
        await self.wait_until_writeable()

    async def _do_proxy_connect(self, remote_addr):
        request = Request(
            ver=SocksVersion.SOCKS5,
            cmd=Command.CONNECT,
            atyp=ATYP.IPV4,
            dst_addr=remote_addr[0],
            dst_port=remote_addr[1],
        )
        await self.send(request.to_bytes())

        initial_reply = await self.recv(4)

        if len(initial_reply) < 4:
            raise ValueError("Incomplete SOCKS5 reply header received.")

        atyp = ATYP(initial_reply[3])

        if atyp == ATYP.IPV4:
            remaining_length = 6
        elif atyp == ATYP.DOMAIN_NAME:
            domain_length_byte = await self.recv(1)
            domain_length = domain_length_byte[0] if domain_length_byte else 0
            remaining_length = 1 + domain_length + 2
        elif atyp == ATYP.IPV6:
            remaining_length = 18
        else:
            raise ValueError("Invalid ATYP received.")

        remaining_data = await self.recv(remaining_length)
        full_reply = initial_reply + remaining_data

        reply = Reply.from_bytes(full_reply)
        if not reply.is_ok():
            raise ProxyConnectionError

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
