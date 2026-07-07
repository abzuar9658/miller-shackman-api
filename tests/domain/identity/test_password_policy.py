from app.domain.identity.password_policy import (
    PasswordPolicy,
    PasswordPolicyReasonCode,
    evaluate_password_policy,
)


def test_password_with_minimum_length_is_accepted() -> None:
    decision = evaluate_password_policy("12345678")

    assert decision.accepted is True
    assert decision.reasons == ()


def test_password_shorter_than_minimum_length_is_rejected() -> None:
    decision = evaluate_password_policy("short")

    assert decision.accepted is False
    assert decision.reasons == (PasswordPolicyReasonCode.TOO_SHORT,)


def test_policy_can_raise_minimum_length() -> None:
    decision = evaluate_password_policy(
        "12345678",
        PasswordPolicy(minimum_length=10),
    )

    assert decision.accepted is False
    assert decision.reasons == (PasswordPolicyReasonCode.TOO_SHORT,)