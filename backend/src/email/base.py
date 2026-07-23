from abc import ABC, abstractmethod


class EmailProvider(ABC):

    @abstractmethod
    async def send(self, *, to: str, subject: str, body: str) -> None:
        ...
