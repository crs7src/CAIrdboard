import asyncio

import httpx

from app.ai import Mode
from app.ai.errors import ProviderError, request_json
from app.stages.planner import CommandResult, CommandTimeout

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_TOKENS = 16000
LABEL = "Google Gemini"


def _headers(api_key: str) -> dict[str, str]:
    # The key goes in a header, never in the URL, so it cannot leak into errors.
    return {"x-goog-api-key": api_key, "content-type": "application/json"}


async def verify(api_key: str, model: str) -> None:
    """Fetch the model's metadata: free, and fails for a bad key or unknown model."""
    async with httpx.AsyncClient(timeout=30) as client:
        await request_json(
            client,
            "GET",
            f"{BASE_URL}/models/{model}",
            label=LABEL,
            secret=api_key,
            headers=_headers(api_key),
        )


class GeminiProvider:
    """Generative Language API (generateContent), called directly over HTTPS."""

    id = "gemini"
    label = LABEL

    def __init__(self, api_key: str, model: str, *, max_iterations: int = 20):
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations

    async def run(
        self, prompt: str, cwd: str, timeout: float, mode: Mode = "plan"
    ) -> CommandResult:
        try:
            async with asyncio.timeout(timeout):
                text = await self._complete(prompt, cwd)
        except TimeoutError as e:
            raise CommandTimeout from e
        except ProviderError as e:
            return CommandResult(1, "", str(e))
        if not text.strip():
            return CommandResult(1, "", f"{LABEL} returned no text")
        return CommandResult(0, text, "")

    async def _complete(self, prompt: str, cwd: str) -> str:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS},
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            data = await self._generate(client, body)
        return _text(_content(data))

    async def _generate(self, client, body: dict) -> dict:
        return await request_json(
            client,
            "POST",
            f"{BASE_URL}/models/{self.model}:generateContent",
            label=LABEL,
            secret=self.api_key,
            headers=_headers(self.api_key),
            json=body,
        )


def _content(data: dict) -> dict:
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise ProviderError(
            f"{LABEL} returned no answer" + (f" (blocked: {reason})" if reason else "")
        )
    return candidates[0].get("content") or {}


def _text(content: dict) -> str:
    return "".join(p.get("text", "") for p in content.get("parts") or [])
