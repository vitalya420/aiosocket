import socket
import typing
from dataclasses import dataclass, field

from .exceptions import NoAcceptableMethods

from .abc import ClientMessage, ServerMessage
from .enums import SocksVersion, Method, Command, ATYP, ReplyStatus


@dataclass
class Hello(ClientMessage):
    ver: SocksVersion
    methods: typing.List[int] = field(default_factory=list)

    @property
    def nmethods(self) -> int:
        return len(self.methods)

    def to_bytes(self):
        method_count = self.nmethods
        if method_count > 255:
            raise ValueError("Number of methods cannot exceed 255.")
        return bytes([self.ver, method_count]) + bytes(self.methods)


@dataclass
class HelloResponse(ServerMessage):
    ver: SocksVersion
    method: Method

    @classmethod
    def from_bytes(cls, data: bytes) -> "HelloResponse":
        if len(data) < 2:
            raise ValueError("Data must be at least 2 bytes long.")

        ver = SocksVersion(data[0])
        method = Method(data[1])

        return cls(ver=ver, method=method)

    def raise_exception_if_occurred(self):
        if self.method == Method.NO_ACCEPTABLE_METHODS:
            raise NoAcceptableMethods(
                "No acceptable methods are available. Have you forgot to provide your credentials?"
            )

    def requires_credentials(self):
        return self.method == Method.USERNAME_PASSWORD


@dataclass
class UsernamePassword(ClientMessage):
    ver: SocksVersion
    username: str
    password: str

    def to_bytes(self) -> bytes:
        username = self.username.encode("utf-8")
        password = self.password.encode("utf-8")

        username_length = len(username)
        password_length = len(password)

        if username_length > 255 or password_length > 255:
            raise ValueError(
                "Username and password lengths must not exceed 255 characters."
            )

        return (
            bytes([self.ver])
            + bytes([username_length])
            + username
            + bytes([password_length])
            + password
        )


@dataclass
class AuthenticationResponse(ServerMessage):
    ver: SocksVersion
    status: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "AuthenticationResponse":
        if len(data) < 2:
            raise ValueError("Data must be at least 2 bytes long.")

        ver = SocksVersion(data[0])
        status = data[1]

        return cls(ver=ver, status=status)

    def is_ok(self) -> bool:
        return self.status == 0


@dataclass
class Request(ClientMessage):
    ver: SocksVersion
    cmd: Command
    atyp: ATYP
    dst_addr: str
    dst_port: int

    def _get_address_bytes(self) -> bytes:
        if self.atyp == ATYP.IPV4:
            return socket.inet_aton(self.dst_addr)
        elif self.atyp == ATYP.DOMAIN_NAME:
            return bytes([len(self.dst_addr)]) + self.dst_addr.encode()
        elif self.atyp == ATYP.IPV6:
            return socket.inet_pton(socket.AF_INET6, self.dst_addr)
        else:
            raise ValueError("Invalid address type.")

    def to_bytes(self) -> bytes:
        addr_bytes = self._get_address_bytes()
        port_bytes = self.dst_port.to_bytes(2, "big")

        return bytes([self.ver, self.cmd, 0x00, self.atyp]) + addr_bytes + port_bytes


@dataclass
class Reply:
    ver: SocksVersion
    rep: ReplyStatus
    atyp: ATYP
    bind_addr: str
    bind_port: int

    def is_ok(self):
        return self.rep == ReplyStatus.SUCCESS

    @classmethod
    def from_bytes(cls, data: bytes) -> "Reply":
        if len(data) < 7:
            raise ValueError("Data must be at least 7 bytes long.")

        ver = SocksVersion(data[0])
        rep = ReplyStatus(data[1])
        atyp = ATYP(data[3])

        if atyp == ATYP.IPV4:
            if len(data) < 10:
                raise ValueError("Data is too short for IPv4 address.")
            bind_addr = socket.inet_ntoa(data[4:8])
            bind_port = int.from_bytes(data[8:10], "big")
        elif atyp == ATYP.DOMAIN_NAME:
            addr_length = data[4]
            if len(data) < 5 + addr_length + 2:
                raise ValueError("Data is too short for the domain name and port.")
            bind_addr = data[5 : 5 + addr_length].decode()
            bind_port = int.from_bytes(data[5 + addr_length : 7 + addr_length], "big")
        elif atyp == ATYP.IPV6:
            if len(data) < 22:
                raise ValueError("Data is too short for IPv6 address.")
            bind_addr = socket.inet_ntop(socket.AF_INET6, data[4:20])
            bind_port = int.from_bytes(data[20:22], "big")
        else:
            raise ValueError("Invalid address type.")

        return cls(
            ver=ver, rep=rep, atyp=atyp, bind_addr=bind_addr, bind_port=bind_port
        )
