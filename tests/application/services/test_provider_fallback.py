from app.application.ports.messaging import ProviderFailureKind
from app.application.services.provider_fallback import provider_fallback_allowed
from app.domain.compliance.contactability import ContactChannel


def test_fallback_is_allowed_only_for_a_different_channel_after_permanent_failure() -> None:
    assert provider_fallback_allowed(
        primary_channel=ContactChannel.SMS,
        fallback_channel=ContactChannel.EMAIL,
        failure_kind=ProviderFailureKind.PERMANENT,
    ) is True


def test_temporary_and_uncertain_failures_never_select_fallback() -> None:
    for failure_kind in (
        ProviderFailureKind.TEMPORARY,
        ProviderFailureKind.UNCERTAIN,
        None,
    ):
        assert provider_fallback_allowed(
            primary_channel=ContactChannel.SMS,
            fallback_channel=ContactChannel.EMAIL,
            failure_kind=failure_kind,
        ) is False


def test_same_channel_and_missing_fallback_are_not_fallbacks() -> None:
    assert provider_fallback_allowed(
        primary_channel=ContactChannel.EMAIL,
        fallback_channel=ContactChannel.EMAIL,
        failure_kind=ProviderFailureKind.PERMANENT,
    ) is False
    assert provider_fallback_allowed(
        primary_channel=ContactChannel.EMAIL,
        fallback_channel=None,
        failure_kind=ProviderFailureKind.PERMANENT,
    ) is False
