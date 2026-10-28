import asyncio

import httpx

from app.ai import Mode
from app.ai.errors import ProviderError, request_json
from app.ai.tools import MAX_AGENT_ITERATIONS, MAX_ITERATIONS, ToolBox, tool_specs
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

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_iterations: int = MAX_ITERATIONS,
        max_agent_iterations: int = MAX_AGENT_ITERATIONS,
    ):
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations
        self.max_agent_iterations = max_agent_iterations

    async def run(
        self, prompt: str, cwd: str, timeout: float, mode: Mode = "plan"
    ) -> CommandResult:
        try:
            async with asyncio.timeout(timeout):
                text = await self._complete(prompt, cwd, mode)
        except TimeoutError as e:
            raise CommandTimeout from e
        except ProviderError as e:
            return CommandResult(1, "", str(e))
        if not text.strip():
            return CommandResult(1, "", f"{LABEL} returned no text")
        return CommandResult(0, text, "")

    async def _complete(self, prompt: str, cwd: str, mode: Mode) -> str:
        agent = mode == "agent"
        toolbox = ToolBox(cwd, agent=agent) if mode != "summary" else None
        limit = self.max_agent_iterations if agent else self.max_iterations
        contents: list[dict] = [{"role": "user", "parts": [{"text": prompt}]}]
        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            for _ in range(limit):
                body: dict = {
                    "contents": contents,
                    "generationConfig": {"maxOutputTokens": MAX_TOKENS},
                }
                if toolbox:
                    body["tools"] = [{"functionDeclarations": tool_specs(agent)}]
                data = await self._generate(client, body)
                content = _content(data)
                calls = [
                    p["functionCall"]
                    for p in content.get("parts") or []
                    if "functionCall" in p
                ]
                if toolbox and calls:
                    contents.append(content)
                    parts = [
                        {
                            "functionResponse": {
                                "name": c.get("name", ""),
                                "response": {
                                    # Tools can block (bash), so keep them off the event loop.
                                    "result": await asyncio.to_thread(
                                        toolbox.call, c.get("name", ""), c.get("args")
                                    )
                                },
                            }
                        }
                        for c in calls
                    ]
                    contents.append({"role": "user", "parts": parts})
                    continue
                if _finish_reason(data) == "MAX_TOKENS":
                    raise ProviderError(f"{LABEL} cut its answer off (too long)")
                return _text(content)
        raise ProviderError(f"{LABEL} did not finish within {limit} tool steps")

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


def _finish_reason(data: dict) -> str:
    return ((data.get("candidates") or [{}])[0]).get("finishReason") or ""


def _text(content: dict) -> str:
    return "".join(p.get("text", "") for p in content.get("parts") or [])
