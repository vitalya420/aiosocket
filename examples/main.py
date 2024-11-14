import asyncio
import socket
import ssl

from aiosocket import AsyncSocket
from aiosocket.http import read_http_response
from aiosocket.ssl import wrap_async_socket

TOR_PROXY = ('127.0.0.1', 9050)
HOST = 'api.ipify.org'
ADDRESS = (socket.gethostbyname(HOST), 443)
SSL_CONTEXT = ssl.create_default_context()


request = (
    "GET / HTTP/1.1\r\n"
    f"Host: {HOST}\r\n"
    "\r\n"
).encode()

async def main():
    
    async_sock = AsyncSocket(socket.AF_INET, socket.SOCK_STREAM)
    await async_sock.socks5_connect(TOR_PROXY)
    await async_sock.connect(ADDRESS)
    async_ssl_socket = await wrap_async_socket(
        async_sock, server_hostname=HOST, context=SSL_CONTEXT
    )
    
    await async_ssl_socket.send(request)
    response = await read_http_response(async_ssl_socket)
    print(response.body.decode())


if __name__ == "__main__":
    asyncio.run(main())