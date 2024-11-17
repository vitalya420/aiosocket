import asyncio
import socket
import ssl
import time

from aiosocket.aiosocket2 import AsyncSocket, AsyncSSLSocket, wrap_async_socket
from aiosocket.http.reader import read_http_response


async def bg_task():
    # Background task to check is not async blocked somewhere
    while True:
        print("Ok")
        await asyncio.sleep(2)


def timeit(f):

    async def timed(*args, **kw):

        ts = time.time()
        result = await f(*args, **kw)
        te = time.time()

        print("func:%r args:[%r, %r] took: %2.4f sec" % (f.__name__, args, kw, te - ts))
        return result

    return timed


HOST = "httpbin.org"
ADDR = (HOST, 80)


async def create_socket():
    sock = AsyncSocket(socket.AF_INET, socket.SOCK_STREAM)
    # await sock.socks5_connect(("127.0.0.1", 9050))
    await sock.connect(ADDR)
    return sock


async def main():
    sock = await create_socket()
    print(sock.getpeername())


if __name__ == "__main__":
    asyncio.run(main())
