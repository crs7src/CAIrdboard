import asyncio

import httpx

from app.ai import Mode
from app.ai.errors import ProviderError, request_json
from app.ai.tools import MAX_AGENT_ITERATIONS, MAX_ITERATIONS, ToolBox, tool_specs
from app.stages.planner import CommandResult, CommandTimeout

BASE_URL = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"
MAX_TOKENS = 16000
LABEL = "Anthropic"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": VERSION,
        "content-type": "application/json",
    }


async def verify(api_key: str, model: str) -> None:
    """List models: free, and fails with 401 for a bad key."""
    async with httpx.AsyncClient(timeout=30) as client:
        await request_json(
            client,
            "GET",
            f"{BASE_URL}/models",
            label=LABEL,
            secret=api_key,
            headers=_headers(api_key),
        )


class AnthropicProvider:
    """Anthropic Messages API, called directly over HTTPS."""

    id = "anthropic"
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
        messages: list[dict] = [{"role": "user", "content": prompt}]
        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            for _ in range(limit):
                body = {
                    "model": self.model,
                    "max_tokens": MAX_TOKENS,
                    "messages": messages,
                }
                if toolbox:
                    body["tools"] = [
                        {
                            "name": t["name"],
                            "description": t["description"],
                            "input_schema": t["parameters"],
                        }
                        for t in tool_specs(agent)
                    ]
                data = await request_json(
                    client,
                    "POST",
                    f"{BASE_URL}/messages",
                    label=LABEL,
                    secret=self.api_key,
                    headers=_headers(self.api_key),
                    json=body,
                )
                blocks = data.get("content") or []
                if toolbox and data.get("stop_reason") == "tool_use":
                    messages.append({"role": "assistant", "content": blocks})
                    results = [
                        {
                            "type": "tool_result",
                            "tool_use_id": b.get("id"),
                            # Tools can block (bash), so keep them off the event loop.
                            "content": await asyncio.to_thread(
                                toolbox.call, b.get("name", ""), b.get("input")
                            ),
                        }
                        for b in blocks
                        if b.get("type") == "tool_use"
                    ]
                    messages.append({"role": "user", "content": results})
                    continue
                if data.get("stop_reason") == "max_tokens":
                    raise ProviderError(f"{LABEL} cut its answer off (too long)")
                return _text(data)
        raise ProviderError(f"{LABEL} did not finish within {limit} tool steps")


def _text(data: dict) -> str:
    return "".join(
        block.get("text", "")
        for block in data.get("content") or []
        if block.get("type") == "text"
    )
