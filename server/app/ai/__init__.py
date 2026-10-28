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


def api_key_for(settings, provider_id: str) -> str:
    return getattr(settings, f"{provider_id}_api_key", "") or ""


def is_configured(settings, provider_id: str) -> bool:
    return provider_id == "copilot" or bool(api_key_for(settings, provider_id))


def model_for(config, provider_id: str) -> str | None:
    return (
        config.provider_models.get(provider_id) or PROVIDERS[provider_id].default_model
    )


async def verify_key(provider_id: str, api_key: str, model: str) -> None:
    """Check a key with a cheap call; raises ProviderError when it is not accepted."""
    from app.ai import anthropic, gemini

    await {"anthropic": anthropic, "gemini": gemini}[provider_id].verify(api_key, model)


def make_provider(provider_id: str, settings, runner, model: str | None = None):
    """Build the provider, or raise ProviderNotConfigured when it has no API key."""
    from app.ai.copilot import CopilotProvider

    if provider_id not in PROVIDERS:
        raise ProviderNotConfigured(f"Unknown AI provider '{provider_id}'")
    if provider_id == "copilot":
        return CopilotProvider(settings.copilot_command, runner)
    key = api_key_for(settings, provider_id)
    if not key:
        raise ProviderNotConfigured(
            f"{PROVIDERS[provider_id].label} has no API key. "
            "Add one in Settings > AI providers."
        )
    model = model or PROVIDERS[provider_id].default_model
    from app.ai import anthropic, gemini

    cls = {"anthropic": anthropic.AnthropicProvider, "gemini": gemini.GeminiProvider}
    return cls[provider_id](key, model)
