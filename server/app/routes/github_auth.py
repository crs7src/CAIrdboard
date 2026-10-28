from fastapi import APIRouter

from app.deps import (
    SettingsDep,
)
from app.integrations import github
from app.routes.host_credentials import (
    HostCredentialsUpdate,
    _host_status,
    _update_host_credentials,
)

router = APIRouter()


@router.get("/api/github/status")
async def github_status(settings: SettingsDep) -> dict:
    return await _host_status(
        settings, "github", github.fetch_current_user, github.GitHubError
    )


@router.put("/api/github/credentials")
async def update_github_credentials(
    body: HostCredentialsUpdate, settings: SettingsDep
) -> dict:
    """Update the stored GitHub credentials; verified against GitHub before saving."""
    return await _update_host_credentials(
        body, settings, "github", github.fetch_current_user
    )
