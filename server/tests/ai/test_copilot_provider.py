from types import SimpleNamespace

from app.ai import PROVIDERS, make_provider, resolve_provider_id
from app.ai.copilot import CopilotProvider
from app.core.ai_config import AiConfig
from app.stages import implementer, planner, tester
from app.stages.planner import CommandResult


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, args, cwd, timeout):
        self.calls.append((args, cwd, timeout))
        return CommandResult(0, "out", "")


async def test_copilot_builds_the_same_argv_as_the_stages():
    runner = Recorder()
    provider = CopilotProvider("copilot", runner)
    await provider.run("P", "/repo", 5, "plan")
    await provider.run("P", "/repo", 5, "test")
    await provider.run("P", "/repo", 5, "summary")
    await provider.run("P", "/repo", 5, "agent")
    argvs = [c[0] for c in runner.calls]
    assert argvs == [
        planner.build_args("copilot", "P"),
        tester.build_args("copilot", "P"),
        implementer.summary_args("copilot", "P"),
        implementer.build_args("copilot", "P"),
    ]
    assert runner.calls[0][1:] == ("/repo", 5)


def test_registry_and_default_resolution():
    assert set(PROVIDERS) == {"copilot", "anthropic", "gemini"}
    assert PROVIDERS["copilot"].supports_agent
    assert PROVIDERS["anthropic"].supports_agent
    assert PROVIDERS["gemini"].supports_agent
    assert resolve_provider_id(AiConfig(), "ABC") == "copilot"


def test_resolve_project_default_and_fallback():
    config = AiConfig(default_provider="gemini", project_providers={"abc": "anthropic"})
    assert resolve_provider_id(config, "ABC") == "anthropic"
    assert resolve_provider_id(config, "XYZ") == "gemini"
    # An id removed from the registry falls back to Copilot.
    stale = SimpleNamespace(project_providers={"ABC": "gone"}, default_provider="x")
    assert resolve_provider_id(stale, "ABC") == "copilot"


def test_make_provider_copilot_uses_configured_command():
    provider = make_provider("copilot", SimpleNamespace(copilot_command="cp"), None)
    assert provider.command == "cp"
