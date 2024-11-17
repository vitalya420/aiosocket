import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Proxy:
    chain_index: int
    addr: Tuple[str, int]
    credentials: Optional[Tuple[str, str]] = None
    connect_time: float


class ProxyChain(deque[Proxy]):
    def print(self):
        for proxy in self:
            print(
                f"Proxy {proxy.chain_index}: {proxy.addr}, Time: {proxy.connect_time:.2f}s"
            )


class SOCKS5SocketMixin(ABC):
    """
    Class to inherit for socket class

    class MySocket(socket.socket, SOCKS5SocketMixin):
        pass
    """

    def __init__(self):
        super().__init__()
        self.proxy_chain = ProxyChain()

    def socks5_connect(
        self, addr: Tuple[str, int], credentials: Optional[Tuple[str, str]] = None
    ):
        start = time.time()
        self.do_socks5_connect(addr, credentials)
        end = time.time()
        proxy_info = Proxy(len(self.proxy_chain), addr, credentials, end - start)
        self.proxy_chain.append(proxy_info)

    @abstractmethod
    def do_socks5_connect(
        self, addr: Tuple[str, int], credentials: Optional[Tuple[str, str]] = None
    ):
        pass

    def get_proxy_chain(self) -> ProxyChain:
        return self.proxy_chain
