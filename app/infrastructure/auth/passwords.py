import bcrypt


class PasslibPasswordHasher:
    def __init__(self, *, bcrypt_rounds: int = 12) -> None:
        self._bcrypt_rounds = bcrypt_rounds

    def hash_password(self, password: str) -> str:
        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt(rounds=self._bcrypt_rounds)
        return bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
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
