from app.application.ports.messaging import ProviderFailureKind


def classify_http_status(status_code: int) -> ProviderFailureKind:
    if status_code in {408, 409, 425, 429} or status_code >= 500:
        return ProviderFailureKind.TEMPORARY if status_code < 500 else ProviderFailureKind.UNCERTAIN
    if 400 <= status_code < 500:
        return ProviderFailureKind.PERMANENT
    return ProviderFailureKind.UNCERTAIN
