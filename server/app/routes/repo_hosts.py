from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator, model_validator

from app.core.ai_config import load_ai_config
from app.core.config import (
    Settings,
)
from app.deps import (
    SettingsDep,
    _db,
)
from app.integrations import hosting, remotes
from app.integrations.remotes import HostError, HostProject
from app.routes.tests import _project_repo

router = APIRouter()


class RepoHostBody(BaseModel):
    provider: hosting.Provider
    path: str

    @field_validator("path")
    @classmethod
    def clean_path(cls, v: str) -> str:
        return v.strip().strip("/").removesuffix(".git")

    @model_validator(mode="after")
    def valid_path(self) -> RepoHostBody:
        if self.provider == "github":
            if not remotes.REPO_PATH_RE.match(self.path):
                raise ValueError("Use the repository path, like owner/repo")
        elif not remotes.PROJECT_PATH_RE.match(self.path):
            raise ValueError("Use the project path, like group/subgroup/project")
        return self


async def _repo_host(settings: Settings, project: str, repo: str) -> hosting.RepoHost:
    return await hosting.resolve(settings, _db(settings), project, repo)


@router.get("/api/repo-hosts")
async def list_repo_hosts(settings: SettingsDep) -> list[hosting.RepoHost]:
    """Every Jira project with a repo, and the GitLab/GitHub project it maps to."""
    repos = load_ai_config(settings.ai_config_file).project_repos
    return [
        await _repo_host(settings, project, repo)
        for project, repo in sorted(repos.items())
    ]


@router.get("/api/repo-hosts/{project}")
async def get_repo_host(project: str, settings: SettingsDep) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    return await _repo_host(settings, project.upper(), repo)


@router.put("/api/repo-hosts/{project}")
async def put_repo_host(
    project: str, body: RepoHostBody, settings: SettingsDep
) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    project = project.upper()
    hosting.Mappings(_db(settings)).set(project, body.provider, body.path)
    return await _repo_host(settings, project, repo)


@router.delete("/api/repo-hosts/{project}")
async def delete_repo_host(project: str, settings: SettingsDep) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    project = project.upper()
    hosting.Mappings(_db(settings)).delete(project)
    return await _repo_host(settings, project, repo)


@router.get("/api/repo-hosts/{project}/check")
async def check_repo_host(project: str, settings: SettingsDep) -> HostProject:
    """Confirm the token can see the mapped project and report its default branch."""
    repo = _project_repo(settings, project)
    host = await _repo_host(settings, project.upper(), repo)
    if host.provider is None or host.path is None:
        raise HTTPException(
            409,
            "No GitLab or GitHub project is known for this repo. Set one in Settings.",
        )
    if not hosting.configured(settings, host.provider):
        raise HTTPException(
            503,
            f"{hosting.LABELS[host.provider]} is not configured. Add your credentials in Settings.",
        )
    try:
        return await hosting.fetch_project(settings, host.provider, host.path)
    except HostError as e:
        raise HTTPException(502, str(e)) from e
