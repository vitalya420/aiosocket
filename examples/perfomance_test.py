import asyncio
import socket
import ssl
import time
from typing import Optional, Tuple

from aiosocket import AsyncSocket, AsyncSSLSocket
from aiosocket.http import read_http_response
from aiosocket.ssl import wrap_async_socket

TOR_PROXY = ("127.0.0.1", 9050)
HOST = "api.ipify.org"
ADDRESS = (socket.gethostbyname(HOST), 443)
SSL_CONTEXT = ssl.create_default_context()


request = ("GET / HTTP/1.1\r\n" f"Host: {HOST}\r\n" "\r\n").encode()


async def get_my_ip(sock: AsyncSSLSocket):
    await sock.send(request)
    response = await read_http_response(sock)
    print(response.body.decode())


async def do_requests_concurrently(sockets):
    return await asyncio.gather(
        *[get_my_ip(sock) for sock in sockets], return_exceptions=True
    )


async def create_socket(addr: Tuple, proxy: Optional[Tuple[str, int]] = None):
    async_sock = AsyncSocket(socket.AF_INET, socket.SOCK_STREAM)
    if proxy:
        await async_sock.socks5_connect(proxy)
    await async_sock.connect(addr)
    async_ssl_socket = await wrap_async_socket(
        async_sock, server_hostname=HOST, context=SSL_CONTEXT
    )
    return async_ssl_socket


async def create_sockets_concurrently(
    addr, amount: int, proxy: Optional[Tuple[str, int]] = None
):
    sockets = await asyncio.gather(*[create_socket(addr, proxy) for _ in range(amount)])
    return sockets


async def main():
    k = 500
    start = time.time()
    sockets = await create_sockets_concurrently(addr=ADDRESS, amount=k)
    end = time.time()
    print(f"{k} async ssl sockets created in {end-start:02f} seconds.")
    # 500 async ssl sockets created in 6 - 8 seconds.
    # with no ssl handshake it takes between ~ 0.25 seconds - 1.12 seconds to create 500 sockets

    start = time.time()
    res = await do_requests_concurrently(sockets)
    end = time.time()
    exc_count = sum(1 for result in res if isinstance(result, Exception))
    print(
        f"{len(sockets)} concurrent socket requests done in {end-start:02f} seconds. Exceptions: {exc_count}"
    )
    # ~ 4 seconds

    start = time.time()
    proxy_sockets = await create_sockets_concurrently(
        addr=ADDRESS, proxy=TOR_PROXY, amount=k
    )
    end = time.time()
    print(f"{k} async ssl sockets with proxy created in {end-start:02f} seconds.")
    # 500 async ssl sockets with proxy created in 6 - 8 seconds.

    start = time.time()
    res = await do_requests_concurrently(proxy_sockets)
    end = time.time()
    exc_count = sum(1 for result in res if isinstance(result, Exception))
    print(
        f"{len(proxy_sockets)} concurrent socket requests done in {end-start:02f} seconds. Exceptions: {exc_count}"
    )
    # ~ 4 seconds


if __name__ == "__main__":
    asyncio.run(main())
