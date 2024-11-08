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
        "POST /api/v1/exchange-point HTTP/1.1\r\n"
    )

    data = json.dumps({
        'recipient_phone': '+380956409567',
        'points': 1499,
        'comment': '',
    })

    content_len = len(data.encode())
    headers = {
        'user-agent': 'Android:11;version:1.12.0;Google sdk_gphone_x86',
        'accept': 'application/json',
        'authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpYXQiOjE3MzEwMTM5OTAsImV4cCI6MTczMzY0MTk5MCwicm9sZXMiOlsiUk9MRV9DTElFTlQiXSwidG9rZW5JZGVudGlmaWVyU3RyaW5nIjoiKzM4MDk2MTU3NDM2OEAxNzMxMDEzOTkwIn0.PaqfvySPedRJKEJ2xjahbMF8xU7EMaRxgzkO4Yc5u-9t5hfJ4DYjDmmSlJrScbpWCLnlSMEbhN2Grk-jQiPpyFSTDY-EiiZ4evPiOfRuZsobqt6aXhRFJ21sy0T-S1q3Y34JuuDEom0fgrZ0mdqLNN6AisWbn_2lcCKIhUkH3kAk84hiVHc8XNmdYRSKBypNzNgxeJLpLEyNgZVMCbmZw3x8k6BPVz99wOEhcamJ4FOIQ8NyyaUW2_jpv3_CNPLhxzymPtHI6XUWC-rXBa4DPAuMnFiek8IqwRTZNJujsIXjEHg9ZdBUOrEXjutYnkF_lDo__5T-q6Zvs954QGtWqfRW5g29Xj-U-E_ASXhkYvoLyRWfA-i3XHYsq5XD8JchoKrdwpPai7eaRjG7Yz0zD5R_opes7LUp4GuneObN-LUHhBDwAbCimGS-wzrw4fpbzQ6c84vfk8H2U4KNMUycRFawjMd0oweHSPQGsu9PJJS-98jidz2pRNdNq98oI_pqgtQjUiC87T598_jsE5rMkHBvtATVJCN_8h9nACAewj3Ij1c8kYH7U30OneIN0rtGfqmb3Uw5OsOe-tLYq6-x2AckHsAJC1mSp_zKA_br43GFv76MVmHe5KnTiG-A919PXdgO6gnUUXCf3X0MysOepHy7v-3A8AkK3rck-6UAa2k',
        'content-type': 'application/json',
        'content-length': content_len,
        'host': HOST
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
    sockets = await asyncio.gather(*[open_socket() for _ in range(100)], return_exceptions=True)
    # sockets = [await open_socket() for i in range(200)]
    end = time.time()
    print(end - start)
    start = time.time()
    res = await asyncio.gather(*[do_request2(sock) for sock in sockets if isinstance(sock, AsyncSSLSocket)],
                               return_exceptions=True)
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
