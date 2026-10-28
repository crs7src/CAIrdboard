"""AI providers: how a prompt becomes text. Copilot CLI is the default."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.stages.planner import CommandResult

# What the call is for. The Copilot CLI picks its tool permissions from it.
Mode = Literal["plan", "test", "summary"]

DEFAULT_PROVIDER = "copilot"


class AiProvider(Protocol):
    id: str
    label: str

    async def run(
        self, prompt: str, cwd: str, timeout: float, mode: Mode = "plan"
    ) -> CommandResult: ...


class ProviderNotConfigured(Exception):
    pass


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    default_model: str | None
    # Whether it can run the agent stages (implement, review, feedback).
    supports_agent: bool


PROVIDERS: dict[str, ProviderInfo] = {
    "copilot": ProviderInfo("copilot", "GitHub Copilot CLI", None, True),
    "anthropic": ProviderInfo("anthropic", "Anthropic", "claude-sonnet-4-5", False),
    "gemini": ProviderInfo("gemini", "Google Gemini", "gemini-2.5-pro", False),
}


def resolve_provider_id(config, project_key: str | None) -> str:
    """The project's provider, else the default, else Copilot."""
    for candidate in (
        config.project_providers.get((project_key or "").upper()),
        config.default_provider,
    ):
        if candidate in PROVIDERS:
            return candidate
    return DEFAULT_PROVIDER


def make_provider(provider_id: str, settings, runner) -> AiProvider:
    """Build the provider, or raise ProviderNotConfigured when it has no API key."""
    from app.ai.copilot import CopilotProvider

    if provider_id == "copilot":
        return CopilotProvider(settings.copilot_command, runner)
    raise ProviderNotConfigured(f"Unknown AI provider '{provider_id}'")
