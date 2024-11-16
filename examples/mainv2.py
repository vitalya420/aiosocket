import asyncio
import socket
from aiosocket.aiosocket2 import AsyncSocket


async def bg_task():
    # Background task to check is not async blocked somewhere
    while True:
        print("Ok")
        await asyncio.sleep(2)


async def echo_for_client(conn):
    print("connection", conn, conn.fileno())
    while True:
        print("recv")
        data = await conn.recv(0xFFFF)
        print("data", data)
        if not data:
            break
        await conn.send(data)


async def main():
    loop = asyncio.get_event_loop()
    # loop.create_task(bg_task())
    sock = AsyncSocket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 12346))
    sock.listen(5)
    while True:
        conn, _ = await sock.accept()
        loop.create_task(echo_for_client(conn))


if __name__ == "__main__":
    asyncio.run(main())
