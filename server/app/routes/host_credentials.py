from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app import (
    hosting,
)
from app.config import (
    GITHUB_FIELDS,
    GITLAB_FIELDS,
    Settings,
    save_credentials,
)
from app.remotes import HostError

router = APIRouter()


class HostCredentialsUpdate(BaseModel):
    url: str | None = None
    token: str | None = None

    @field_validator("url", "token")
    @classmethod
    def not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def valid_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Must start with http:// or https://")
        return v.rstrip("/")


async def _host_status(
    settings: Settings, provider: hosting.Provider, fetch_user, error
) -> dict:
    url = settings.gitlab_url if provider == "gitlab" else settings.github_url
    is_configured = hosting.configured(settings, provider)
    status = {"configured": is_configured, "connected": False, "user": None, "url": url}
    if not is_configured:
        return status
    try:
        status["user"] = await fetch_user(settings)
        status["connected"] = True
    except error:
        pass
    return status


async def _update_host_credentials(
    body: HostCredentialsUpdate,
    settings: Settings,
    provider: hosting.Provider,
    fetch_user,
) -> dict:
    """Verify the merged credentials against the host, then save them."""
    label = hosting.LABELS[provider]
    prefix = provider
    fields = GITLAB_FIELDS if provider == "gitlab" else GITHUB_FIELDS
    file = (
        settings.gitlab_credentials_file
        if provider == "gitlab"
        else settings.github_credentials_file
    )
    updates = {f"{prefix}_url": body.url, f"{prefix}_token": body.token}
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise HTTPException(422, "Provide at least one of url, token")
    candidate = settings.model_copy(update=updates)
    if not hosting.configured(candidate, provider):
        raise HTTPException(422, f"{label} URL and token are both required")
    try:
        user = await fetch_user(candidate)
    except HostError as e:
        raise HTTPException(
            400, f"{label} did not accept these credentials: {e}"
        ) from e
    save_credentials(file, updates, fields)
    return {"connected": True, "user": user}
