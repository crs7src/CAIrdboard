from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app import (
    jira,
)
from app.config import (
    save_credentials,
)
from app.deps import (
    SettingsDep,
)

router = APIRouter()


class CredentialsUpdate(BaseModel):
    base_url: str | None = None
    email: str | None = None
    token: str | None = None

    @field_validator("base_url", "email", "token")
    @classmethod
    def not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Must start with http:// or https://")
        return v.rstrip("/")


@router.get("/api/jira/status")
async def jira_status(settings: SettingsDep) -> dict:
    status = {
        "configured": settings.jira_configured,
        "connected": False,
        "user": None,
        "base_url": settings.jira_base_url,
        "email": settings.jira_email,
    }
    if not settings.jira_configured:
        return status
    try:
        status["user"] = await jira.fetch_current_user(settings)
        status["connected"] = True
    except jira.JiraError:
        pass
    return status


@router.put("/api/jira/credentials")
async def update_credentials(body: CredentialsUpdate, settings: SettingsDep) -> dict:
    """Update the stored Jira credentials; omitted fields keep their current value.

    The merged result is verified against Jira before anything is saved.
    """
    updates = {
        "jira_base_url": body.base_url,
        "jira_email": body.email,
        "jira_api_token": body.token,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise HTTPException(422, "Provide at least one of base_url, email, token")
    candidate = settings.model_copy(update=updates)
    if not candidate.jira_configured:
        raise HTTPException(422, "Site URL, email and token are all required")
    try:
        user = await jira.fetch_current_user(candidate)
    except jira.JiraError as e:
        raise HTTPException(400, f"Jira did not accept these credentials: {e}") from e
    save_credentials(settings.jira_credentials_file, updates)
    return {"connected": True, "user": user}
