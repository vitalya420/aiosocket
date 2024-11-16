import asyncio
import socket
from typing import Optional, Tuple

from .exceptions import NotAllowedError
from .socks5.exceptions import (
    ProxyError,
    ProxyConnectionError,
    ProxyAuthenticationError,
)
from .socks5.helper import (
    request_to_connect_to_remote_address,
    loads_reply,
    craft_hello_message,
    loads_hello_response,
    craft_username_password_message,
    loads_authentication_response,
)
from .utils import wait_sock_ready_to_read, wait_sock_ready_to_write, read_reply_bytes


class AsyncSocket(socket.socket):
    """
    An asynchronous implementation of socket.socket that provides non-blocking I/O operations.

    This class extends the standard socket.socket to provide async/await support for network operations.
    It includes support for SOCKS5 proxy connections and implements custom timeout handling.

    Attributes:
        _async_timeout (Optional[float]): Custom timeout value for async operations
        _socks5_address (Optional[Tuple[str, int]]): Address of the SOCKS5 proxy if used
        _socks5_is_connected (bool): Flag indicating if connected to SOCKS5 proxy
        _socks5_credentials (Optional[Tuple[str, str]]): Username and password for SOCKS5 proxy
    """

    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
        """
        Initialize an async socket instance.

        Args:
            family (int, optional): Address family. Defaults to -1.
            type (int, optional): Socket type. Defaults to -1.
            proto (int, optional): Protocol number. Defaults to -1.
            fileno (int, optional): File descriptor. Defaults to None.
        """
        super().__init__(family, type, proto, fileno)
        super().setblocking(False)

        self._async_timeout: Optional[float] = None
        self._socks5_address: Optional[Tuple[str, int]] = None
        self._socks5_is_connected: bool = False
        self._socks5_credentials: Optional[Tuple[str, str]] = None

    async def send(self, data: bytes, flags: int = 0) -> int:
        """
        Asynchronously send data to the socket.

        Args:
            data (bytes): The bytes to send
            flags (int, optional): Send flags. Defaults to 0.

        Returns:
            int: The number of bytes sent

        Note:
            This method will keep trying to send all data, handling BlockingIOError
            by awaiting until the socket is writable.
        """
        total_sent = 0
        need_to_send = len(data)

        while total_sent < need_to_send:
            try:
                total_sent += super().send(data, flags)
            except BlockingIOError:
                await self.wait_until_writeable()
        return total_sent

    async def recv(self, bufsize: int, flags: int = 0) -> bytes:
        """
        Asynchronously receive data from the socket with optional timeout.

        Args:
            bufsize (int): The maximum amount of data to receive
            flags (int, optional): Receive flags. Defaults to 0.

        Returns:
            bytes: The received data

        Raises:
            TimeoutError: If the operation exceeds the socket's timeout value
        """
        if self._async_timeout is not None:
            try:
                return await asyncio.wait_for(
                    self._recv(bufsize, flags), self._async_timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Timeout reading response")
        else:
            return await self._recv(bufsize, flags)

    async def _recv(self, bufsize: int, flags: int = 0) -> bytes:
        """
        Internal method to handle asynchronous receive operations.

        Returns data as soon as any is available, instead of waiting for the full buffer.

        Args:
            bufsize (int): The maximum amount of data to receive
            flags (int, optional): Receive flags. Defaults to 0.

        Returns:
            bytes: The received data, or empty bytes if connection closed
        """
        data = bytearray()

        while True:
            try:
                chunk = super().recv(bufsize - len(data), flags)
                if not chunk:
                    return bytes(data) if data else b""

                data.extend(chunk)
                return bytes(data)

            except BlockingIOError:
                if data:
                    return bytes(data)
                await self.wait_until_readable()
            except ConnectionError:
                return bytes(data) if data else b""

    async def accept(self) -> Tuple["AsyncSocket", Tuple[str, int]]:
        """
        Asynchronously accept a connection on the socket.

        Returns:
            Tuple[AsyncSocket, Tuple[str, int]]: A tuple containing the new AsyncSocket object
            and the address of the client.
        """
        await self.wait_until_readable()
        fd, addr = super()._accept()

        async_sock = self.__class__(self.family, self.type, self.proto, fileno=fd)
        async_sock.setblocking(False)
        return async_sock, addr

    async def _do_socks5_connect(
        self, sock5_addr: Tuple[str, int], credentials: Optional[Tuple[str, str]] = None
    ) -> None:
        """
        Internal method to establish a SOCKS5 proxy connection.

        Args:
            sock5_addr (Tuple[str, int]): Address of the SOCKS5 proxy server
            credentials (Optional[Tuple[str, str]], optional): Username and password for authentication.
                Defaults to None.

        Raises:
            RuntimeError: If credentials are required but not provided
            ProxyAuthenticationError: If authentication fails
        """
        await self._do_connect(sock5_addr)
        hello = craft_hello_message(credentials)
        await self.send(hello.to_bytes())

        response = loads_hello_response(await self.recv(2))
        response.raise_exception_if_occurred()

        if response.requires_credentials():
            if credentials is None:
                raise RuntimeError(
                    "Credentials are not provided but it should not happen"
                )
            auth_message = await craft_username_password_message(*credentials)
            await self.send(auth_message.to_bytes())
            if not loads_authentication_response(await self.recv(2)).is_ok():
                raise ProxyAuthenticationError("Authentication failed")
        self._socks5_address = sock5_addr
        self._socks5_is_connected = True
        self._socks5_credentials = credentials

    async def socks5_connect(
        self,
        sock5_addr: Tuple[str, int],
        credentials: Optional[Tuple[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """
        Connect to a remote host through a SOCKS5 proxy.

        Args:
            sock5_addr (Tuple[str, int]): Address of the SOCKS5 proxy server
            credentials (Optional[Tuple[str, str]], optional): Username and password for authentication.
                Defaults to None.
            timeout (Optional[float], optional): Connection timeout in seconds. Defaults to None.

        Raises:
            NotImplementedError: If UDP association is attempted
            TimeoutError: If connection times out
            ProxyConnectionError: If connection to proxy is refused
        """
        if socket.SOCK_DGRAM == self.type:
            raise NotImplementedError("UDP associate is not implemented yet, sorry.")
        try:
            if timeout:
                await asyncio.wait_for(
                    self._do_socks5_connect(sock5_addr, credentials), timeout
                )
            else:
                await self._do_socks5_connect(sock5_addr, credentials)
        except TimeoutError:
            raise TimeoutError(f"Timeout during connecting to proxy {sock5_addr}")
        except ConnectionRefusedError:
            raise ProxyConnectionError(f"Connection to proxy {sock5_addr} refused")
        finally:
            self._socks5_is_connected = False
            self._socks5_address = None
            self._socks5_credentials = None

    async def _do_connect(self, address: Tuple[str, int]) -> None:
        """
        Internal method to establish a connection to an address.

        Args:
            address (Tuple[str, int]): The address to connect to
        """
        if self._socks5_is_connected:
            return await self._connect_via_proxy(address)
        super().connect_ex(address)
        await self.wait_until_writeable()

    async def connect(self, address: Tuple[str, int]) -> None:
        """
        Asynchronously connect to a remote address.

        Args:
            address (Tuple[str, int]): The address to connect to

        Raises:
            TimeoutError: If connection attempt times out
        """
        if self._async_timeout:
            try:
                return await asyncio.wait_for(
                    self._do_connect(address), self._async_timeout
                )
            except TimeoutError:
                raise TimeoutError(f"Timeout during connection to {address}")
        return await self._do_connect(address)

    def settimeout(self, value: Optional[float]) -> None:
        """
        Set a timeout on blocking socket operations.

        Args:
            value (Optional[float]): Timeout in seconds, or None to disable timeout
        """
        self._async_timeout = value

    def setblocking(self, flag: bool) -> None:
        """
        Set the socket to blocking or non-blocking mode.

        Args:
            flag (bool): If True, set to blocking mode

        Raises:
            NotAllowedError: If attempting to set blocking mode to True
        """
        if flag:
            raise NotAllowedError(
                "Blocking async socket will make it just a regular socket"
            )

    async def wait_until_writeable(self) -> None:
        """Wait until the socket is ready for writing."""
        return await wait_sock_ready_to_write(self.fileno())

    async def wait_until_readable(self) -> None:
        """Wait until the socket is ready for reading."""
        return await wait_sock_ready_to_read(self.fileno())

    async def _connect_via_proxy(self, address: Tuple[str, int]) -> None:
        """
        Internal method to connect to a remote address through an established SOCKS5 proxy.

        Args:
            address (Tuple[str, int]): The target address to connect to

        Raises:
            ProxyError: If the proxy fails to establish the connection
        """
        message = request_to_connect_to_remote_address(address)
        await self.send(message.to_bytes())
        reply_bytes = await read_reply_bytes(self)
        reply = loads_reply(reply_bytes)
        if not reply.is_ok():
            raise ProxyError(
                f"Proxy {self._socks5_address} was unable to connect to {address}"
            )
