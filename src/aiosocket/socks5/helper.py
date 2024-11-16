import ipaddress
from typing import List, Optional, Tuple

from .enums import Method, SocksVersion, ATYP, Command
from .messages import (
    Hello,
    HelloResponse,
    UsernamePassword,
    AuthenticationResponse,
    Request,
    Reply,
)


def guess_atyp(destination: str) -> ATYP:
    try:
        ipaddress.IPv4Address(destination)
        return ATYP.IPV4
    except ipaddress.AddressValueError:
        pass

    try:
        ipaddress.IPv6Address(destination)
        return ATYP.IPV6
    except ipaddress.AddressValueError:
        pass

    return ATYP.DOMAIN_NAME


def craft_hello_message(credentials: Optional[Tuple[str, str]] = None) -> Hello:
    method = (
        Method.USERNAME_PASSWORD
        if credentials is not None
        else Method.NO_AUTHENTICATION_REQUIRED
    )
    return Hello(ver=SocksVersion.SOCKS5, methods=[method])


def loads_hello_response(data: bytes) -> HelloResponse:
    return HelloResponse.from_bytes(data)


def craft_username_password_message(username: str, password: str) -> UsernamePassword:
    return UsernamePassword(
        ver=SocksVersion.SOCKS5, username=username, password=password
    )


def loads_authentication_response(data: bytes) -> AuthenticationResponse:
    return AuthenticationResponse.from_bytes(data)


def request_to_connect_to_remote_address(
    addr: Tuple[str, int], atyp: Optional[ATYP] = None
) -> Request:
    atyp = atyp or guess_atyp(addr[0])
    request = Request(
        ver=SocksVersion.SOCKS5,
        cmd=Command.CONNECT,
        atyp=atyp,
        dst_addr=addr[0],
        dst_port=addr[1],
    )
    return request


def loads_reply(data: bytes) -> Reply:
    return Reply.from_bytes(data)
