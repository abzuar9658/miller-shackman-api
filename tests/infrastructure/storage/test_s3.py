import pytest

from app.infrastructure.storage.s3.client import S3StorageProvider


class _FakeBody:
    def read(self) -> bytes:
        return b"file content"


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> S3StorageProvider:
    s3 = S3StorageProvider("bucket", "us-east-1")
    monkeypatch.setattr(s3._client, "put_object", lambda **kwargs: None)
    monkeypatch.setattr(s3._client, "get_object", lambda **kwargs: {"Body": _FakeBody()})
    monkeypatch.setattr(s3._client, "delete_object", lambda **kwargs: None)
    monkeypatch.setattr(
        s3._client,
        "generate_presigned_url",
        lambda _operation, **kwargs: "https://example.com/bucket/key",
    )
    return s3


async def test_upload_returns_key(provider: S3StorageProvider) -> None:
    result = await provider.upload("reports/1.pdf", b"data", "application/pdf")
    assert result == "reports/1.pdf"


async def test_download_returns_bytes(provider: S3StorageProvider) -> None:
    result = await provider.download("reports/1.pdf")
    assert result == b"file content"


async def test_delete_does_not_raise(provider: S3StorageProvider) -> None:
    await provider.delete("reports/1.pdf")


async def test_get_url_returns_string(provider: S3StorageProvider) -> None:
    result = await provider.get_url("reports/1.pdf")
    assert result == "https://example.com/bucket/key"
