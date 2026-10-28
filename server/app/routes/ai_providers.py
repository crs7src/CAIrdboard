from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.ai import PROVIDERS, api_key_for, is_configured, model_for, verify_key
from app.ai.errors import ProviderError
from app.auth.credentials import AI_FIELDS, remove_credentials, save_credentials
from app.core.ai_config import AiConfig, load_ai_config, save_ai_config
from app.core.config import Settings
from app.deps import SettingsDep

router = APIRouter()


class ProviderStatus(BaseModel):
    id: str
    label: str
    configured: bool
    model: str | None
    default_model: str | None
    needs_key: bool
    supports_agent: bool


class ProviderCredentialsUpdate(BaseModel):
    api_key: str | None = None
    model: str | None = None

    @field_validator("api_key", "model")
    @classmethod
    def not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v


class DefaultProviderBody(BaseModel):
    provider: Literal["copilot", "anthropic", "gemini"]


def _status(settings: Settings, config: AiConfig, provider_id: str) -> ProviderStatus:
    info = PROVIDERS[provider_id]
    return ProviderStatus(
        id=provider_id,
        label=info.label,
        configured=is_configured(settings, provider_id),
        model=model_for(config, provider_id),
        default_model=info.default_model,
        needs_key=provider_id != "copilot",
        supports_agent=info.supports_agent,
    )


def _api_provider(provider_id: str) -> str:
    if provider_id not in PROVIDERS:
        raise HTTPException(422, f"Unknown AI provider '{provider_id}'")
    if provider_id == "copilot":
        raise HTTPException(422, "GitHub Copilot CLI needs no API key")
    return provider_id


@router.get("/api/ai/providers")
def list_providers(settings: SettingsDep) -> list[ProviderStatus]:
    config = load_ai_config(settings.ai_config_file)
    return [_status(settings, config, p) for p in PROVIDERS]


@router.put("/api/ai/providers/{provider_id}/credentials")
async def put_provider_credentials(
    provider_id: str, body: ProviderCredentialsUpdate, settings: SettingsDep
) -> ProviderStatus:
    """Verify the key (when there is one) with the provider, then save it."""
    provider_id = _api_provider(provider_id)
    if body.api_key is None and body.model is None:
        raise HTTPException(422, "Provide at least one of api_key, model")
    config = load_ai_config(settings.ai_config_file)
    key = body.api_key or api_key_for(settings, provider_id)
    model = body.model or model_for(config, provider_id) or ""
    if key:
        try:
            await verify_key(provider_id, key, model)
        except ProviderError as e:
            raise HTTPException(400, str(e)) from e
    if body.api_key:
        save_credentials(
            settings.ai_credentials_file,
            {f"{provider_id}_api_key": body.api_key},
            AI_FIELDS,
        )
    if body.model:
        config.provider_models[provider_id] = body.model
        save_ai_config(settings.ai_config_file, config)
    saved = settings.model_copy(update={f"{provider_id}_api_key": key})
    return _status(saved, config, provider_id)


@router.delete("/api/ai/providers/{provider_id}/credentials")
def delete_provider_credentials(
    provider_id: str, settings: SettingsDep
) -> ProviderStatus:
    """Forget the saved key (a key from .env still applies)."""
    provider_id = _api_provider(provider_id)
    field = f"{provider_id}_api_key"
    remove_credentials(settings.ai_credentials_file, (field,))
    env_only = Settings()  # what is left: a key from the environment or .env
    return _status(env_only, load_ai_config(settings.ai_config_file), provider_id)


@router.get("/api/ai/providers/{provider_id}/check")
async def check_provider(provider_id: str, settings: SettingsDep) -> dict[str, bool]:
    provider_id = _api_provider(provider_id)
    key = api_key_for(settings, provider_id)
    if not key:
        raise HTTPException(
            503, f"{PROVIDERS[provider_id].label} has no API key configured"
        )
    config = load_ai_config(settings.ai_config_file)
    try:
        await verify_key(provider_id, key, model_for(config, provider_id) or "")
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True}


@router.put("/api/ai/default")
def put_default_provider(body: DefaultProviderBody, settings: SettingsDep) -> AiConfig:
    config = load_ai_config(settings.ai_config_file)
    config.default_provider = body.provider
    save_ai_config(settings.ai_config_file, config)
    return config
