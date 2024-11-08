import typing
from abc import ABC, abstractmethod


class BaseMessage:
    pass


class ClientMessage(BaseMessage, ABC):

    @abstractmethod
    def to_bytes(self) -> bytes:
        pass


class ServerMessage(BaseMessage, ABC):

    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes) -> "ServerMessage":
        pass
