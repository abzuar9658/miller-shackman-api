from dataclasses import dataclass
from enum import StrEnum


class PasswordPolicyReasonCode(StrEnum):
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class PasswordPolicy:
    minimum_length: int = 8


@dataclass(frozen=True)
class PasswordPolicyDecision:
    accepted: bool
    reasons: tuple[PasswordPolicyReasonCode, ...] = ()


def evaluate_password_policy(
    password: str,
    policy: PasswordPolicy | None = None,
) -> PasswordPolicyDecision:
    active_policy = policy or PasswordPolicy()
    reasons: list[PasswordPolicyReasonCode] = []

    if len(password) < active_policy.minimum_length:
        reasons.append(PasswordPolicyReasonCode.TOO_SHORT)

    return PasswordPolicyDecision(
        accepted=not reasons,
        reasons=tuple(reasons),
    )