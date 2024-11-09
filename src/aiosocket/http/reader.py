import socket
from select import select

from aiosocket.async_socket import AIOSocket
from .response import HTTPResponse


async def read_http_response(
    sock: socket.socket | AIOSocket,
) -> HTTPResponse:
    headers_buff = b""
    while b"\r\n\r\n" not in headers_buff:
        chunk = await sock.recv(1)
        if not chunk:
            raise ConnectionError(
                f"Connection closed while reading headers. Header Buff: {headers_buff}. {res}"
            )
        headers_buff += chunk

    headers_str = headers_buff.decode("utf-8")
    header_lines = headers_str.split("\r\n")

    status_line = header_lines[0]
    http_version, status_code, *status_phrase = status_line.split(" ")
    status_code = int(status_code)
    status_phrase = " ".join(status_phrase)

    headers_dict = {}
    for line in header_lines[1:]:
        if line:
            key, value = line.split(": ", 1)
            headers_dict[key.lower()] = value

    is_chunked = headers_dict.get("transfer-encoding", "").lower() == "chunked"

    body = b""

    if is_chunked:
        while True:
            chunk_size_str = b""
            while b"\r\n" not in chunk_size_str:
                chunk = await sock.recv(1)
                if not chunk:
                    raise ConnectionError("Connection closed while reading chunk size")
                chunk_size_str += chunk

            chunk_size_hex = chunk_size_str.decode("utf-8").strip()
            chunk_size = int(chunk_size_hex, 16)

            if chunk_size == 0:
                break

            chunk_data = b""
            bytes_read = 0
            while bytes_read < chunk_size:
                chunk = await sock.recv(chunk_size - bytes_read)
                if not chunk:
                    raise ConnectionError("Connection closed while reading chunk data")
                chunk_data += chunk
                bytes_read += len(chunk)

                body += chunk_data

                await sock.recv(2)
    else:
        content_length = int(headers_dict.get("content-length", 0))
        bytes_read = 0
        while bytes_read < content_length:
            chunk_size = min(4096, content_length - bytes_read)
            chunk = await sock.recv(chunk_size)
            if not chunk:
                raise ConnectionError("Connection closed while reading body")
            body += chunk
            bytes_read += len(chunk)

    return HTTPResponse(
        http_version=http_version,
        status_code=status_code,
        status_phrase=status_phrase,
        headers=headers_dict,
        body=body,
    )
