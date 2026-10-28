class ProviderError(Exception):
    """A provider call failed. The message is safe to show: it never holds the key."""


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "[redacted]") if secret else text


def http_error(label: str, status: int, detail: str, secret: str) -> ProviderError:
    """Turn an HTTP failure into a clear message."""
    if status in (401, 403):
        why = "did not accept the API key. Check it in Settings > AI providers"
    elif status == 429:
        why = "rate limit or quota reached. Try again later"
    elif status >= 500:
        why = f"is having problems (HTTP {status}). Try again later"
    else:
        why = f"rejected the request (HTTP {status})"
    message = f"{label} {why}."
    if status not in (401, 403) and detail:
        message += f" {redact(detail, secret)[:300]}"
    return ProviderError(message)
