from app.application.ports.messaging import ProviderFailureKind
from app.domain.compliance.contactability import ContactChannel


def provider_fallback_allowed(
    *,
    primary_channel: ContactChannel,
    fallback_channel: ContactChannel | None,
    failure_kind: ProviderFailureKind | None,
) -> bool:
    """Allow exactly one fallback only after a permanent pre-acceptance failure."""
    return (
        fallback_channel is not None
        and fallback_channel is not primary_channel
        and failure_kind is ProviderFailureKind.PERMANENT
    )
