import asyncio
import socket
import errno
import ssl
from socket import SOCK_STREAM
from socket import SOL_SOCKET, SO_TYPE
from typing import List, Optional, Tuple
import warnings

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

        # Storing proxy chain as list of tuples, like address and credentials
        # [ (<addr>, <creds>) ]
        self._socks5_proxies_chain: List[Tuple[Tuple[str, int], Tuple[str, str]]] = []

        self._async_connect = self.connect
        self._peer_address: Optional[Tuple[str, int]] = None

    async def socks5_bind(self):
        pass

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
        await self.connect(sock5_addr)
        hello = craft_hello_message(credentials)
        await self.send(hello.to_bytes())

        response = loads_hello_response(await self.recv(2))
        response.raise_exception_if_occurred()

        if response.requires_credentials():
            if credentials is None:
                raise RuntimeError(
                    "Credentials are not provided but it should not happen"
                )
            auth_message = craft_username_password_message(*credentials)
            await self.send(auth_message.to_bytes())
            if not (
                response := loads_authentication_response(await self.recv(2))
            ).is_ok():
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

            self._socks5_proxies_chain.append((sock5_addr, credentials))
        except TimeoutError:
            raise TimeoutError(f"Timeout during connecting to proxy {sock5_addr}")
        except ConnectionRefusedError:
            raise ProxyConnectionError(f"Connection to proxy {sock5_addr} refused")

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
                await asyncio.wait_for(self._do_connect(address), self._async_timeout)
            except TimeoutError:
                raise TimeoutError(f"Timeout during connection to {address}")
        await self._do_connect(address)

    def settimeout(self, value: Optional[float]) -> None:
        """
        Set a timeout on blocking socket operations.

        Args:
            value (Optional[float]): Timeout in seconds, or None to disable timeout
        """
        self._async_timeout = value

    def gettimeout(self):
        return self._async_timeout

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

    def get_proxy_chain(self):
        return self._socks5_proxies_chain

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
        print(reply)
        if not reply.is_ok():
            raise ProxyError(
                f"Proxy {self._socks5_address} was unable to connect to {address}"
            )
        self._peer_address = address


class AsyncSSLSocket(AsyncSocket):
    """This class implements a subtype of socket.socket that wraps
    the underlying OS socket in an SSL context when necessary, and
    provides read and write methods over that channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    async def _create(
        cls,
        sock,
        server_side=False,
        do_handshake_on_connect=True,
        suppress_ragged_eofs=True,
        server_hostname=None,
        context=None,
        session=None,
    ):
        if sock.getsockopt(SOL_SOCKET, SO_TYPE) != SOCK_STREAM:
            raise NotImplementedError("only stream sockets are supported")
        if server_side:
            if server_hostname:
                raise ValueError(
                    "server_hostname can only be specified " "in client mode"
                )
            if session is not None:
                raise ValueError("session can only be specified in " "client mode")
        if context.check_hostname and not server_hostname:
            raise ValueError("check_hostname requires server_hostname")

        sock_timeout = sock.gettimeout()
        kwargs = dict(
            family=sock.family, type=sock.type, proto=sock.proto, fileno=sock.fileno()
        )
        self = cls(**kwargs)
        sock.detach()
        try:
            self._context = context
            self._session = session
            self._closed = False
            self._sslobj = None
            self.server_side = server_side
            self.server_hostname = context._encode_hostname(server_hostname)
            self.do_handshake_on_connect = do_handshake_on_connect
            self.suppress_ragged_eofs = suppress_ragged_eofs

            # See if we are connected
            try:
                self.getpeername()
            except OSError as e:
                if e.errno != errno.ENOTCONN:
                    raise
                connected = False
                try:
                    # We are not connected so this is not supposed to block, but
                    # testing revealed otherwise on macOS and Windows so we do
                    # the non-blocking dance regardless. Our raise when any data
                    # is found means consuming the data is harmless.
                    notconn_pre_handshake_data = await self.recv(1)
                except OSError as e:
                    # EINVAL occurs for recv(1) on non-connected on unix sockets.
                    if e.errno not in (errno.ENOTCONN, errno.EINVAL):
                        raise
                    notconn_pre_handshake_data = b""
                if notconn_pre_handshake_data:
                    # This prevents pending data sent to the socket before it was
                    # closed from escaping to the caller who could otherwise
                    # presume it came through a successful TLS connection.
                    reason = "Closed before TLS handshake with data in recv buffer."
                    notconn_pre_handshake_data_error = ssl.SSLError(e.errno, reason)
                    # Add the SSLError attributes that _ssl.c always adds.
                    notconn_pre_handshake_data_error.reason = reason
                    notconn_pre_handshake_data_error.library = None
                    try:
                        raise notconn_pre_handshake_data_error
                    finally:
                        # Explicitly break the reference cycle.
                        notconn_pre_handshake_data_error = None
            else:
                connected = True

            self.settimeout(sock_timeout)  # Must come after setblocking() calls.
            self._connected = connected
            if connected:
                # create the SSL object
                self._sslobj = self._context._wrap_socket(
                    self,
                    server_side,
                    self.server_hostname,
                    owner=self,
                    session=self._session,
                )
                if do_handshake_on_connect:
                    timeout = self.gettimeout()
                    if timeout == 0.0:
                        # non-blocking
                        raise ValueError(
                            "do_handshake_on_connect should not be specified for non-blocking sockets"
                        )
                    self.do_handshake()
        except:
            try:
                self.close()
            except OSError:
                pass
            raise
        return self

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, ctx):
        self._context = ctx
        self._sslobj.context = ctx

    @property
    def session(self):
        if self._sslobj is not None:
            return self._sslobj.session

    @session.setter
    def session(self, session):
        self._session = session
        if self._sslobj is not None:
            self._sslobj.session = session

    @property
    def session_reused(self):
        if self._sslobj is not None:
            return self._sslobj.session_reused

    def dup(self):
        raise NotImplementedError("Can't dup() %s instances" % self.__class__.__name__)

    def _checkClosed(self, msg=None):
        # raise an exception here if you wish to check for spurious closes
        pass

    def _check_connected(self):
        if not self._connected:
            # getpeername() will raise ENOTCONN if the socket is really
            # not connected; note that we can be connected even without
            # _connected being set, e.g. if connect() first returned
            # EAGAIN.
            self.getpeername()

    def read(self, len=1024, buffer=None):
        """Read up to LEN bytes and return them.
        Return zero-length string on EOF."""

        self._checkClosed()
        if self._sslobj is None:
            raise ValueError("Read on closed or unwrapped SSL socket.")
        try:
            if buffer is not None:
                return self._sslobj.read(len, buffer)
            else:
                return self._sslobj.read(len)
        except ssl.SSLError as x:
            if x.args[0] == ssl.SSL_ERROR_EOF and self.suppress_ragged_eofs:
                if buffer is not None:
                    return 0
                else:
                    return b""
            else:
                raise

    def write(self, data):
        """Write DATA to the underlying SSL channel.  Returns
        number of bytes of DATA actually transmitted."""

        self._checkClosed()
        if self._sslobj is None:
            raise ValueError("Write on closed or unwrapped SSL socket.")
        return self._sslobj.write(data)

    def getpeercert(self, binary_form=False):
        self._checkClosed()
        self._check_connected()
        return self._sslobj.getpeercert(binary_form)

    def selected_npn_protocol(self):
        self._checkClosed()
        warnings.warn(
            "ssl NPN is deprecated, use ALPN instead", DeprecationWarning, stacklevel=2
        )
        return None

    def selected_alpn_protocol(self):
        self._checkClosed()
        if self._sslobj is None or not ssl.HAS_ALPN:
            return None
        else:
            return self._sslobj.selected_alpn_protocol()

    def cipher(self):
        self._checkClosed()
        if self._sslobj is None:
            return None
        else:
            return self._sslobj.cipher()

    def shared_ciphers(self):
        self._checkClosed()
        if self._sslobj is None:
            return None
        else:
            return self._sslobj.shared_ciphers()

    def compression(self):
        self._checkClosed()
        if self._sslobj is None:
            return None
        else:
            return self._sslobj.compression()

    async def ssl_send(self, data, flags=0):
        self._checkClosed()
        if self._sslobj is not None:
            if flags != 0:
                raise ValueError(
                    "non-zero flags not allowed in calls to send() on %s"
                    % self.__class__
                )
            return self._sslobj.write(data)
        else:
            return await super().send(data, flags)

    async def send(self, data, flags=0):
        total_sent = 0
        need_to_send = len(data)

        while total_sent < need_to_send:
            try:
                sent = await self.ssl_send(data, flags)
                total_sent += sent
            except ssl.SSLWantWriteError:
                await self.wait_until_writeable()
            except ssl.SSLWantReadError:
                await self.wait_until_readable()
        return total_sent

    def sendto(self, data, flags_or_addr, addr=None):
        self._checkClosed()
        if self._sslobj is not None:
            raise ValueError("sendto not allowed on instances of %s" % self.__class__)
        elif addr is None:
            return super().sendto(data, flags_or_addr)
        else:
            return super().sendto(data, flags_or_addr, addr)

    def sendmsg(self, *args, **kwargs):
        # Ensure programs don't send data unencrypted if they try to
        # use this method.
        raise NotImplementedError(
            "sendmsg not allowed on instances of %s" % self.__class__
        )

    def sendall(self, data, flags=0):
        self._checkClosed()
        if self._sslobj is not None:
            if flags != 0:
                raise ValueError(
                    "non-zero flags not allowed in calls to sendall() on %s"
                    % self.__class__
                )
            count = 0
            with memoryview(data) as view, view.cast("B") as byte_view:
                amount = len(byte_view)
                while count < amount:
                    v = self.send(byte_view[count:])
                    count += v
        else:
            return super().sendall(data, flags)

    def sendfile(self, file, offset=0, count=None):
        """Send a file, possibly by using os.sendfile() if this is a
        clear-text socket.  Return the total number of bytes sent.
        """
        if self._sslobj is not None:
            return self._sendfile_use_send(file, offset, count)
        else:
            # os.sendfile() works with plain sockets only
            return super().sendfile(file, offset, count)

    async def ssl_recv(self, buflen=1024, flags=0):
        self._checkClosed()
        if self._sslobj is not None:
            if flags != 0:
                raise ValueError(
                    "non-zero flags not allowed in calls to recv() on %s"
                    % self.__class__
                )
            return self.read(buflen)
        else:
            return await super().recv(buflen, flags)

    async def recv(self, buflen=1024, flags=0):
        total_received = 0
        data = b""
        while total_received < buflen:
            try:
                chunk = await self.ssl_recv(buflen - total_received, flags)
                if not chunk:
                    break
                total_received += len(chunk)
                data += chunk
            except ssl.SSLWantWriteError:
                await self.wait_until_writeable()
            except ssl.SSLWantReadError:
                await self.wait_until_readable()
        return data

    def recv_into(self, buffer, nbytes=None, flags=0):
        self._checkClosed()
        if nbytes is None:
            if buffer is not None:
                with memoryview(buffer) as view:
                    nbytes = view.nbytes
                if not nbytes:
                    nbytes = 1024
            else:
                nbytes = 1024
        if self._sslobj is not None:
            if flags != 0:
                raise ValueError(
                    "non-zero flags not allowed in calls to recv_into() on %s"
                    % self.__class__
                )
            return self.read(nbytes, buffer)
        else:
            return super().recv_into(buffer, nbytes, flags)

    def recvfrom(self, buflen=1024, flags=0):
        self._checkClosed()
        if self._sslobj is not None:
            raise ValueError("recvfrom not allowed on instances of %s" % self.__class__)
        else:
            return super().recvfrom(buflen, flags)

    def recvfrom_into(self, buffer, nbytes=None, flags=0):
        self._checkClosed()
        if self._sslobj is not None:
            raise ValueError(
                "recvfrom_into not allowed on instances of %s" % self.__class__
            )
        else:
            return super().recvfrom_into(buffer, nbytes, flags)

    def recvmsg(self, *args, **kwargs):
        raise NotImplementedError(
            "recvmsg not allowed on instances of %s" % self.__class__
        )

    def recvmsg_into(self, *args, **kwargs):
        raise NotImplementedError(
            "recvmsg_into not allowed on instances of " "%s" % self.__class__
        )

    def pending(self):
        self._checkClosed()
        if self._sslobj is not None:
            return self._sslobj.pending()
        else:
            return 0

    def shutdown(self, how):
        self._checkClosed()
        self._sslobj = None
        super().shutdown(how)

    def unwrap(self):
        if self._sslobj:
            s = self._sslobj.shutdown()
            self._sslobj = None
            return s
        else:
            raise ValueError("No SSL wrapper around " + str(self))

    def verify_client_post_handshake(self):
        if self._sslobj:
            return self._sslobj.verify_client_post_handshake()
        else:
            raise ValueError("No SSL wrapper around " + str(self))

    def _real_close(self):
        self._sslobj = None
        super()._real_close()

    def do_handshake(self, block=False):
        self._check_connected()
        timeout = self.gettimeout()
        try:
            if timeout == 0.0 and block:
                self.settimeout(None)
            self._sslobj.do_handshake()
        finally:
            self.settimeout(timeout)

    async def _real_connect(self, addr, connect_ex):
        if self.server_side:
            raise ValueError("can't connect in server-side mode")
        # Here we assume that the socket is client-side, and not
        # connected at the time of the call.  We connect it, then wrap it.
        if self._connected or self._sslobj is not None:
            raise ValueError("attempt to connect already-connected SSLSocket!")
        self._sslobj = self.context._wrap_socket(
            self, False, self.server_hostname, owner=self, session=self._session
        )
        try:
            if connect_ex:
                rc = super().connect_ex(addr)
            else:
                rc = None
                await super().connect(addr)
            if not rc:
                self._connected = True
                if self.do_handshake_on_connect:
                    handshake_completed = False
                    while not handshake_completed:
                        try:
                            self.do_handshake()
                        except ssl.SSLWantReadError:
                            await self.wait_until_readable()
                        except ssl.SSLWantWriteError:
                            await self.wait_until_writeable()
                        handshake_completed = True
            return rc
        except (OSError, ValueError):
            self._sslobj = None
            raise

    async def connect(self, addr):
        """Connects to remote ADDR, and then wraps the connection in
        an SSL channel."""
        await self._real_connect(addr, False)

    def connect_ex(self, addr):
        """Connects to remote ADDR, and then wraps the connection in
        an SSL channel."""
        return self._real_connect(addr, True)

    def accept(self):
        """Accepts a new connection from a remote client, and returns
        a tuple containing that new connection wrapped with a server-side
        SSL channel, and the address of the remote client."""

        newsock, addr = super().accept()
        newsock = self.context.wrap_socket(
            newsock,
            do_handshake_on_connect=self.do_handshake_on_connect,
            suppress_ragged_eofs=self.suppress_ragged_eofs,
            server_side=True,
        )
        return newsock, addr

    def get_channel_binding(self, cb_type="tls-unique"):
        if self._sslobj is not None:
            return self._sslobj.get_channel_binding(cb_type)
        else:
            if cb_type not in ssl.CHANNEL_BINDING_TYPES:
                raise ValueError(
                    "{0} channel binding type not implemented".format(cb_type)
                )
            return None

    def version(self):
        if self._sslobj is not None:
            return self._sslobj.version()
        else:
            return None


async def wrap_async_socket(
    sock: AsyncSocket,
    context: ssl.SSLContext,
    server_side=False,
    do_handshake_on_connect=True,
    suppress_ragged_eofs=True,
    server_hostname=None,
    session=None,
) -> AsyncSSLSocket:
    instance = await AsyncSSLSocket._create(
        sock,
        server_side,
        do_handshake_on_connect,
        suppress_ragged_eofs,
        server_hostname,
        context,
        session,
    )
    return instance
