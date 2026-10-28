import httpx

from app.stages.planner import CommandTimeout


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


async def request_json(
    client, method: str, url: str, *, label: str, secret: str, **kwargs
) -> dict:
    """Send a request and return the JSON body; any failure is a ProviderError.

    A timeout is re-raised as CommandTimeout so stages report it like a CLI timeout.
    """
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException as e:
        raise CommandTimeout from e
    except httpx.HTTPError as e:
        raise ProviderError(
            f"Could not reach {label}: {redact(type(e).__name__, secret)}"
        ) from e
    if response.status_code >= 400:
        detail = ""
        try:
            error = response.json().get("error")
            detail = error.get("message", "") if isinstance(error, dict) else ""
        except ValueError, AttributeError:
            pass
        raise http_error(label, response.status_code, detail, secret)
    try:
        data = response.json()
    except ValueError as e:
        raise ProviderError(f"{label} returned a response that is not JSON") from e
    return data if isinstance(data, dict) else {}
