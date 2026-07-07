from app.infrastructure.auth.passwords import PasslibPasswordHasher


def test_hash_password_and_verify_round_trip() -> None:
    hasher = PasslibPasswordHasher()

    password_hash = hasher.hash_password("super-secret-password")

    assert password_hash != "super-secret-password"
    assert hasher.verify_password("super-secret-password", password_hash) is True
    assert hasher.verify_password("wrong-password", password_hash) is False


def test_needs_rehash_returns_true_for_invalid_hash() -> None:
    hasher = PasslibPasswordHasher()

    assert hasher.needs_rehash("not-a-valid-hash") is True


def test_verify_password_returns_false_for_invalid_hash() -> None:
    hasher = PasslibPasswordHasher()

    assert hasher.verify_password("password", "not-a-valid-hash") is False