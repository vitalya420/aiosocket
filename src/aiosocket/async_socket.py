import asyncio
import socket
import ssl
from typing import Tuple, Optional

from aiosocket.utils import (
    create_nonblocking_socket_and_connect,
    send_to_nonblocking_socket,
    receive_from_nonblocking_socket,
)


class AIOSocket:
    def __init__(
        self, sock: socket.socket, loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self.sock = sock
        self.loop = loop or asyncio.get_event_loop()
        self.is_ssl = isinstance(sock, ssl.SSLSocket)

    async def send(self, data: bytes) -> int:
        return await send_to_nonblocking_socket(self.sock, data)

    async def recv(self, buffer_size: int) -> bytes:
        return await receive_from_nonblocking_socket(self.sock, buffer_size)

    @classmethod
    async def open_connection(
        cls,
        remote_addr: Tuple[str, int],
        ssl_context: Optional[ssl.SSLContext] = None,
        server_hostname: Optional[str] = None,
        socks5_addr: Optional[Tuple[str, int]] = None,
        socks5_credentials: Optional[int] = None,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        sock = await create_nonblocking_socket_and_connect(
            remote_addr, ssl_context, server_hostname, socks5_addr, socks5_credentials
        )
        return cls(sock, loop=loop)
