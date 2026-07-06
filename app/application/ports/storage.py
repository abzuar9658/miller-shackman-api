from typing import Protocol


class FileStorageProvider(Protocol):
    async def upload(self, key: str, content: bytes, content_type: str) -> str:
        """Store content and return the object key."""
        raise NotImplementedError

    async def download(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def get_url(self, key: str) -> str:
        """Return a URL that can be used to fetch the object."""
        raise NotImplementedError
