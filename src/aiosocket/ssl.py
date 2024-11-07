import errno
import ssl
from socket import SOCK_STREAM
from socket import SOL_SOCKET, SO_TYPE

from aiosocket.aiosocket import AsyncSocket


class AsyncSSLSocket(ssl.SSLSocket, AsyncSocket):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raise TypeError(
            f"{self.__class__.__name__} does not have a public "
            f"constructor. Instances are returned by "
            f"SSLContext.wrap_socket()."
        )

    async def recv(self, buflen=1024, flags=0):
        total_received = 0
        data = b""
        while total_received < buflen:
            try:
                chunk = super().recv(buflen - total_received, flags)
                if not chunk:
                    break
                total_received += len(chunk)
                data += chunk
            except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
                await self.wait_until_writeable()
        return data

    async def send(self, data, flags=0):
        total_sent = 0
        need_to_send = len(data)

        while total_sent < need_to_send:
            try:
                total_sent += super().send(data, flags)
            except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
                await self.wait_until_writeable()
        return total_sent

    @classmethod
    def create(
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
        self = cls.__new__(cls, **kwargs)
        super(ssl.SSLSocket, self).__init__(**kwargs)
        sock.detach()
        # Now SSLSocket is responsible for closing the file descriptor.
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
                blocking = self.getblocking()
                self.setblocking(False)
                try:
                    # We are not connected so this is not supposed to block, but
                    # testing revealed otherwise on macOS and Windows so we do
                    # the non-blocking dance regardless. Our raise when any data
                    # is found means consuming the data is harmless.
                    notconn_pre_handshake_data = self.recv(1)
                except OSError as e:
                    # EINVAL occurs for recv(1) on non-connected on unix sockets.
                    if e.errno not in (errno.ENOTCONN, errno.EINVAL):
                        raise
                    notconn_pre_handshake_data = b""
                self.setblocking(blocking)
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


async def wrap_async_socket(
        sock,
        server_side=False,
        suppress_ragged_eofs=True,
        server_hostname=None,
        context=None,
        session=None,
):
    instance = AsyncSSLSocket.create(sock, server_side, False, suppress_ragged_eofs, server_hostname, context, session)
    await instance.wait_until_writeable()
    handshake_completed = False
    while not handshake_completed:
        try:
            instance.do_handshake()
        except ssl.SSLWantReadError:
            await instance.wait_until_readable()
        except ssl.SSLWantWriteError:
            await instance.wait_until_writeable()
        handshake_completed = True
    return instance
