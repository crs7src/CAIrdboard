from fastapi import APIRouter

from app import (
    gitlab,
)
from app.deps import (
    SettingsDep,
)
from app.routes.host_credentials import (
    HostCredentialsUpdate,
    _host_status,
    _update_host_credentials,
)

router = APIRouter()


@router.get("/api/gitlab/status")
async def gitlab_status(settings: SettingsDep) -> dict:
    return await _host_status(
        settings, "gitlab", gitlab.fetch_current_user, gitlab.GitLabError
    )


@router.put("/api/gitlab/credentials")
async def update_gitlab_credentials(
    body: HostCredentialsUpdate, settings: SettingsDep
) -> dict:
    """Update the stored GitLab credentials; verified against GitLab before saving."""
    return await _update_host_credentials(
        body, settings, "gitlab", gitlab.fetch_current_user
    )
