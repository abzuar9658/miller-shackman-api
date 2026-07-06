import pytest

from app.infrastructure.cache.redis.client import RedisCacheProvider


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> RedisCacheProvider:
    cache = RedisCacheProvider("redis://localhost:6379/0")
    monkeypatch.setattr(cache, "_client", _FakeRedis())
    return cache


async def test_set_and_get(provider: RedisCacheProvider) -> None:
    await provider.set("lead:1", "value", 60)
    result = await provider.get("lead:1")
    assert result == "value"


async def test_get_missing_returns_none(provider: RedisCacheProvider) -> None:
    result = await provider.get("lead:missing")
    assert result is None


async def test_delete_removes_key(provider: RedisCacheProvider) -> None:
    await provider.set("lead:1", "value", 60)
    await provider.delete("lead:1")
    result = await provider.get("lead:1")
    assert result is None
