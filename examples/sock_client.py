import asyncio
import socket
import ssl
import time

from aiosocket.async_socket import AIOSocket
from aiosocket.http import read_http_response


async def main():
    host = "httpbin.org"
    addr = (socket.gethostbyname(host), 443)
    ssl_context = ssl.create_default_context()
    proxy = ("127.0.0.1", 9050)  # Tor

    start = time.time()

    body = b"hello world!"
    req = (
        f"POST /post HTTP/1.1\r\nHost: {host}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        + body
    )

    async def _task(use_proxy=True):
        async_sock = await AIOSocket.open_connection(
            addr,
            ssl_context=ssl_context,
            server_hostname=host,
            socks5_addr=proxy if use_proxy else None,
        )
        await async_sock.send(req)
        res = await read_http_response(async_sock)
        return res

    result = await _task()

    end = time.time()

    print(result, end - start)
    # I have result 1-4 seconds via tor socks proxy

    start = time.time()
    res = await asyncio.gather(*[_task() for _ in range(200)])
    end = time.time()
    print(len(res), end - start)
    # 200 responses in ~9 seconds

    start = time.time()
    res = await asyncio.gather(*[_task(use_proxy=False) for _ in range(200)])
    end = time.time()
    print(len(res), end - start)
    # No tor proxy 200 responses in 6.0817389488220215


if __name__ == "__main__":
    asyncio.run(main())
