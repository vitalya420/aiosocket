import asyncio
import socket
import ssl
from typing import TYPE_CHECKING, Tuple, Optional, Literal

from aiosocket.socks5.enums import Method, SocksVersion, Command, ATYP
from aiosocket.socks5.exceptions import (
    NoAcceptableMethods,
    AuthenticationError,
    ProxyConnectionError,
)
from aiosocket.socks5.messages import (
    Hello,
    HelloResponse,
    UsernamePassword,
    AuthenticationResponse,
    Request,
    Reply,
)

if TYPE_CHECKING:
    from .aiosocket2 import AsyncSocket


async def connect_to_proxy(
    sock: socket.socket, addr: Tuple[str, int], credentials: Tuple[str, str]
) -> None:
    sock.connect_ex(addr)
    method = (
        Method.USERNAME_PASSWORD
        if credentials is not None
        else Method.NO_AUTHENTICATION_REQUIRED
    )
    hello = Hello(ver=SocksVersion.SOCKS5, methods=[method]).to_bytes()
    await send_to_nonblocking_socket(sock, hello)
    response_bytes = await receive_from_nonblocking_socket(sock, 2)
    response = HelloResponse.from_bytes(response_bytes)

    if response.method == Method.NO_ACCEPTABLE_METHODS:
        raise NoAcceptableMethods(
            "No acceptable methods are available. Have you forgot to provide your credentials?"
        )

    if response.method == Method.USERNAME_PASSWORD and credentials is not None:
        username, password = credentials
        auth_message = UsernamePassword(username=username, password=password)
        await send_to_nonblocking_socket(sock, auth_message.to_bytes())
        response_bytes = await receive_from_nonblocking_socket(sock, 2)
        if not AuthenticationResponse.from_bytes(response_bytes).is_ok():
            raise AuthenticationError("Authentication failed")


async def proxy_connect_to_address(
    sock: socket.socket, remote_addr: Tuple[str, int]
) -> None:
    request = Request(
        ver=SocksVersion.SOCKS5,
        cmd=Command.CONNECT,
        atyp=ATYP.IPV4,
        dst_addr=remote_addr[0],
        dst_port=remote_addr[1],
    )
    await send_to_nonblocking_socket(sock, request.to_bytes())

    initial_reply = await receive_from_nonblocking_socket(sock, 4)
    if len(initial_reply) < 4:
        raise ValueError("Incomplete SOCKS5 reply header received.")

    atyp = ATYP(initial_reply[3])

    if atyp == ATYP.IPV4:
        remaining_length = 6
    elif atyp == ATYP.DOMAIN_NAME:
        domain_length_byte = await receive_from_nonblocking_socket(sock, 1)
        domain_length = domain_length_byte[0] if domain_length_byte else 0
        remaining_length = 1 + domain_length + 2
    elif atyp == ATYP.IPV6:
        remaining_length = 18
    else:
        raise ValueError("Invalid ATYP received.")

    remaining_data = await receive_from_nonblocking_socket(sock, remaining_length)
    full_reply = initial_reply + remaining_data

    reply = Reply.from_bytes(full_reply)
    if not reply.is_ok():
        raise ProxyConnectionError


async def create_nonblocking_socket_and_connect(
    remote_addr: Tuple[str, int],
    ssl_context: Optional[ssl.SSLContext] = None,
    server_hostname: Optional[str] = None,
    socks5_addr: Optional[Tuple[str, int]] = None,
    socks5_credentials: Optional[Tuple[str, str]] = None,
):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)

    if socks5_addr:
        await connect_to_proxy(sock, socks5_addr, socks5_credentials)
        await proxy_connect_to_address(sock, remote_addr)
    else:
        sock.connect_ex(remote_addr)
        await wait_sock_ready_to_write(sock.fileno())

    if ssl_context and server_hostname:
        sock = ssl_context.wrap_socket(
            sock, do_handshake_on_connect=False, server_hostname=server_hostname
        )
        await wait_sock_ready_to_write(sock.fileno())
        handshake_completed = False
        while not handshake_completed:
            try:
                sock.do_handshake()
            except ssl.SSLWantReadError:
                await wait_sock_ready_to_write(sock.fileno())
            except ssl.SSLWantWriteError:
                await wait_sock_ready_to_write(sock.fileno())
            handshake_completed = True
    return sock


def _socket_ready(
    action: Literal["read", "write"],
    sock_fd: int,
    future: asyncio.Future,
    loop: asyncio.AbstractEventLoop,
):
    func = {"read": loop.remove_reader, "write": loop.remove_writer}[action]
    func(sock_fd)
    future.set_result(None)


async def _wait_socket(
    action: Literal["read", "write"],
    sock_fd: int,
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    loop = loop or asyncio.get_event_loop()
    func = {"read": loop.add_reader, "write": loop.add_writer}[action]
    fut = loop.create_future()
    func(sock_fd, _socket_ready, action, sock_fd, fut, loop)
    return await fut


async def wait_sock_ready_to_read(
    sock_fd: int, loop: Optional[asyncio.AbstractEventLoop] = None
):
    return await _wait_socket("read", sock_fd, loop)


async def wait_sock_ready_to_write(
    sock_fd: int, loop: Optional[asyncio.AbstractEventLoop] = None
):
    return await _wait_socket("write", sock_fd, loop)


async def send_to_nonblocking_socket(sock: socket.socket, data: bytes) -> int:
    total_sent = 0
    need_to_send = len(data)

    if sock.getblocking():
        sock.setblocking(False)

    while total_sent < need_to_send:
        try:
            await wait_sock_ready_to_write(sock.fileno())
            sent = sock.send(data[total_sent:])
            total_sent += sent
        except (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
            await wait_sock_ready_to_write(sock.fileno())

    return total_sent


async def receive_from_nonblocking_socket(
    sock: socket.socket, buffer_size: int
) -> bytes:
    total_received = 0
    data = b""

    if sock.getblocking():
        sock.setblocking(False)

    while total_received < buffer_size:
        try:
            chunk = sock.recv(buffer_size)
            if not chunk:
                break
            total_received += len(chunk)
            data += chunk
        except (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
            await wait_sock_ready_to_read(sock.fileno())

    return data


async def read_reply_bytes(async_socket: "AsyncSocket"):
    initial_reply = await async_socket.recv(4)

    if len(initial_reply) < 4:
        raise ValueError("Incomplete SOCKS5 reply header received.")
    atyp = ATYP(initial_reply[3])
    if atyp == ATYP.IPV4:
        remaining_length = 6
    elif atyp == ATYP.DOMAIN_NAME:
        domain_length_byte = await async_socket.recv(1)
        domain_length = domain_length_byte[0] if domain_length_byte else 0
        remaining_length = 1 + domain_length + 2
    elif atyp == ATYP.IPV6:
        remaining_length = 18
    else:
        raise ValueError("Invalid ATYP received.")
    remaining_data = await async_socket.recv(remaining_length)
    full_reply = initial_reply + remaining_data
    return full_reply
