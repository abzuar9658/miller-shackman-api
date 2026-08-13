import asyncio

import bcrypt


class PasslibPasswordHasher:
    def __init__(self, *, bcrypt_rounds: int = 12) -> None:
        self._bcrypt_rounds = bcrypt_rounds

    async def hash_password(self, password: str) -> str:
        # bcrypt is intentionally CPU-expensive; run it off the event loop.
        return await asyncio.to_thread(self._hash_password_sync, password)

    async def verify_password(self, password: str, password_hash: str) -> bool:
        return await asyncio.to_thread(self._verify_password_sync, password, password_hash)

    def _hash_password_sync(self, password: str) -> str:
        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt(rounds=self._bcrypt_rounds)
        return bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    def _verify_password_sync(self, password: str, password_hash: str) -> bool:
        try:
            return bool(
                bcrypt.checkpw(
                    password.encode("utf-8"),
                    password_hash.encode("utf-8"),
                ),
            )
        except ValueError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            rounds = int(password_hash.split("$")[2])
        except (IndexError, ValueError):
            return True
        return rounds < self._bcrypt_rounds
