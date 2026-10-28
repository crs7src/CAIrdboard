from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError, field_validator

from app.ai import PROVIDERS
from app.core import projects
from app.core.ai_config import AiConfig, load_ai_config, save_ai_config
from app.core.config import (
    Settings,
)
from app.deps import (
    SettingsDep,
    _db,
    _implementation_states,
    _states,
    _test_store,
)
from app.integrations import github, hosting
from app.routes.cards import _load_cards
from app.routes.repo_hosts import RepoHostBody
from app.stages import planner, reviewer, tester

router = APIRouter()


class ProjectBody(BaseModel):
    name: str
    repo_path: str
    # Jira project key; ignored for a GitHub-only project (its key comes from the repo).
    key: str | None = None
    jira_enabled: bool = True
    provider: hosting.Provider | None = None
    host_path: str | None = None
    # AI provider id; blank means the default. Omitted on update keeps the current one.
    ai_provider: str | None = None

    @field_validator("ai_provider")
    @classmethod
    def known_provider(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower()
        if v and v not in PROVIDERS:
            raise ValueError(f"Unknown AI provider '{v}'")
        return v or None

    @field_validator("name", "repo_path")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v

    @field_validator("key", "host_path")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


def _check_repo_path(path: str) -> None:
    if not Path(path).is_absolute():
        raise HTTPException(422, "Repo path must be absolute")
    if not Path(path).is_dir():
        raise HTTPException(422, "Repo path is not a folder on this machine")


def _check_host(provider: str | None, path: str | None) -> hosting.Target | None:
    if provider is None and path is None:
        return None
    if provider is None or path is None:
        raise HTTPException(422, "Set both the git host and its project path")
    try:
        body = RepoHostBody(provider=provider, path=path)
    except ValidationError as e:
        raise HTTPException(
            422, e.errors()[0]["msg"].removeprefix("Value error, ")
        ) from e
    return hosting.Target(provider=body.provider, path=body.path)


def _save_project(
    settings: Settings,
    config: AiConfig,
    key: str,
    body: ProjectBody,
    host: hosting.Target | None,
) -> None:
    config.project_repos[key] = body.repo_path
    config.project_names[key] = body.name
    if body.ai_provider:
        config.project_providers[key] = body.ai_provider
    elif "ai_provider" in body.model_fields_set:
        config.project_providers.pop(key, None)
    save_ai_config(settings.ai_config_file, config)
    mappings = hosting.Mappings(_db(settings))
    if host:
        mappings.set(key, host.provider, host.path)
    else:
        mappings.delete(key)


async def _project(settings: Settings, config: AiConfig, key: str) -> projects.Project:
    return await projects.build_project(settings, _db(settings), config, key)


def _known_project(config: AiConfig, key: str) -> str:
    key = key.upper()
    if key not in config.project_repos:
        raise HTTPException(404, "Project not found")
    return key


@router.get("/api/projects")
async def list_projects(settings: SettingsDep) -> list[projects.Project]:
    """Every project (a repo mapping), without cards so Jira is not called."""
    config = load_ai_config(settings.ai_config_file)
    return [await _project(settings, config, k) for k in sorted(config.project_repos)]


@router.get("/api/projects/{key}")
async def get_project(key: str, settings: SettingsDep) -> projects.Project:
    """One project with its cards. A failing card source becomes card_warnings."""
    config = load_ai_config(settings.ai_config_file)
    key = _known_project(config, key)
    project = await _project(settings, config, key)
    try:
        found, errors = await _load_cards(settings)
    except HTTPException as e:
        found, errors = [], [str(e.detail)]
        if e.status_code == 503:
            errors = []
    db = _db(settings)
    states = {
        "plan": _states(planner.PlanStore(db), planner.recover_stale),
        "implementation": _implementation_states(settings),
        "review": _states(reviewer.ReviewStore(db), reviewer.recover_stale),
        "test": _states(_test_store(settings), tester.recover_stale),
    }
    project.cards = projects.project_cards(found, key, config, states)
    project.card_warnings = "; ".join(errors) or None
    return project


@router.post("/api/projects", status_code=201)
async def create_project(body: ProjectBody, settings: SettingsDep) -> projects.Project:
    _check_repo_path(body.repo_path)
    host = _check_host(body.provider, body.host_path)
    if body.jira_enabled:
        key = (body.key or "").upper()
        if not projects.JIRA_KEY_RE.match(key):
            raise HTTPException(
                422, "Use the Jira project key, like ABC (capital letters and digits)"
            )
    else:
        if host is None or host.provider != "github":
            raise HTTPException(422, "A GitHub-only project needs a GitHub repo path")
        key = github.project_slug(host.path)
    config = load_ai_config(settings.ai_config_file)
    if key in config.project_repos:
        raise HTTPException(409, f"A project with key {key} already exists")
    if not body.jira_enabled and not github.IssueRepos(_db(settings)).claim(
        key, host.path
    ):
        raise HTTPException(409, f"Another GitHub repo already uses the key {key}")
    _save_project(settings, config, key, body, host)
    return await _project(settings, config, key)


@router.put("/api/projects/{key}")
async def update_project(
    key: str, body: ProjectBody, settings: SettingsDep
) -> projects.Project:
    """Change name, repo and host. The key is tied to card keys and runs, so it stays."""
    config = load_ai_config(settings.ai_config_file)
    key = _known_project(config, key)
    _check_repo_path(body.repo_path)
    host = _check_host(body.provider, body.host_path)
    if not projects.is_jira_key(key) and (
        host is None
        or host.provider != "github"
        or github.project_slug(host.path) != key
    ):
        raise HTTPException(
            422, f"A GitHub-only project must stay on a GitHub repo named for {key}"
        )
    _save_project(settings, config, key, body, host)
    return await _project(settings, config, key)


@router.delete("/api/projects/{key}", status_code=204)
def delete_project(key: str, settings: SettingsDep) -> None:
    """Forget the project's setup only; runs, test settings and the repo stay."""
    config = load_ai_config(settings.ai_config_file)
    key = _known_project(config, key)
    config.project_repos.pop(key)
    config.project_names.pop(key, None)
    config.project_providers.pop(key, None)
    save_ai_config(settings.ai_config_file, config)
    hosting.Mappings(_db(settings)).delete(key)
