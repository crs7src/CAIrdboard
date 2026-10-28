from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException

from app.ai import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    AiProvider,
    ProviderNotConfigured,
    make_provider,
    model_for,
    resolve_provider_id,
    with_model,
)
from app.core.ai_config import load_ai_config
from app.core.config import (
    Settings,
    get_settings,
)
from app.core.db import CARD_KEY_RE, Database
from app.stages import feedback, implementer, planner, tester


def _db(settings: Settings) -> Database:
    return Database.at(settings.db_file)


def _test_store(settings: Settings) -> tester.TestStore:
    return tester.TestStore(_db(settings), settings.test_runs_dir)


def _states(store, recover) -> dict[str, str]:
    """Latest state of every card that has a run in the store."""
    states: dict[str, str] = {}
    for key in store.card_keys():
        latest = recover(store, store.latest(key))
        if latest:
            states[key] = latest.state
    return states


def _implementation_states(settings: Settings) -> dict[str, str]:
    """Implementation states; a card whose feedback changes are being made is running."""
    states = _states(
        implementer.ImplementationStore(_db(settings)), implementer.recover_stale
    )
    for key in feedback.ACTIVE:
        if key in states:
            states[key] = "running"
    return states


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_runner(settings: SettingsDep):
    """The command runner; a model chosen for Copilot is added as `--model`."""
    config = load_ai_config(settings.ai_config_file)
    return with_model(
        planner.run_command,
        settings.copilot_command,
        config.provider_models.get("copilot"),
    )


RunnerDep = Annotated[object, Depends(get_runner)]


def _valid_key(key: str) -> str:
    if not CARD_KEY_RE.match(key):
        raise HTTPException(404, "Card not found")
    return key


def _repo_for_key(settings: Settings, key: str) -> str:
    config = load_ai_config(settings.ai_config_file)
    repo = config.repo_for(key.split("-")[0])
    if repo is None or not Path(repo).is_dir():
        raise HTTPException(422, "No valid repo is configured for this card's project")
    return repo


def provider_for(settings: Settings, runner, project: str) -> AiProvider:
    """The AI provider chosen for a project; 503 when it has no API key yet."""
    config = load_ai_config(settings.ai_config_file)
    try:
        provider_id = resolve_provider_id(config, project)
        model = model_for(config, provider_id)
        return make_provider(provider_id, settings, runner, model)
    except ProviderNotConfigured as e:
        raise HTTPException(503, str(e)) from e


def agent_provider_for(settings: Settings, runner, project: str) -> AiProvider:
    """The provider for the agent stages (implement, review, feedback).

    A provider that cannot edit files (Gemini) hands them to Copilot instead; one
    that can (Anthropic) needs its API key, else 503.
    """
    config = load_ai_config(settings.ai_config_file)
    provider_id = resolve_provider_id(config, project)
    if not PROVIDERS[provider_id].supports_agent:
        provider_id = DEFAULT_PROVIDER
    try:
        return make_provider(
            provider_id, settings, runner, model_for(config, provider_id)
        )
    except ProviderNotConfigured as e:
        raise HTTPException(503, str(e)) from e
