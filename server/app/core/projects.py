"""Projects: a name, a local repo, an optional Jira project key and a git host link."""

import re
from pathlib import Path

from pydantic import BaseModel

from app.ai import PROVIDERS, is_configured, resolve_provider_id
from app.core.ai_config import AiConfig
from app.core.config import Settings
from app.core.db import Database
from app.integrations import github, hosting, jira
from app.stages import tester

JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+$")


class SetupItem(BaseModel):
    id: str
    label: str
    done: bool


class ProjectCard(BaseModel):
    key: str
    summary: str
    status: str
    source: str
    url: str
    eligible: bool
    plan_state: str | None = None
    implementation_state: str | None = None
    review_state: str | None = None
    test_state: str | None = None


class Project(BaseModel):
    key: str
    name: str
    repo_path: str
    repo_exists: bool
    jira: bool
    host: hosting.RepoHost
    jira_connected: bool
    gitlab_connected: bool
    github_connected: bool
    test_apps_configured: bool
    # The project's own choice (None: the default) and what is actually used.
    ai_provider: str | None = None
    effective_ai_provider: str = "copilot"
    status: list[SetupItem]
    cards: list[ProjectCard] | None = None
    card_warnings: str | None = None


def is_jira_key(key: str) -> bool:
    return not github.is_issue_key(key)


def _status(
    settings: Settings,
    jira_on: bool,
    repo_exists: bool,
    host: hosting.RepoHost,
    tests: bool,
    ai_provider: str = "copilot",
) -> list[SetupItem]:
    items = [SetupItem(id="repo", label="Local repo found", done=repo_exists)]
    if jira_on:
        items.append(
            SetupItem(id="jira", label="Jira connected", done=settings.jira_configured)
        )
    items.append(
        SetupItem(id="host", label="Git host project set", done=host.path is not None)
    )
    if host.provider:
        items.append(
            SetupItem(
                id="host_credentials",
                label=f"{hosting.LABELS[host.provider]} connected",
                done=hosting.configured(settings, host.provider),
            )
        )
    items.append(SetupItem(id="tests", label="Test apps set", done=tests))
    items.append(
        SetupItem(
            id="ai",
            label=f"AI provider: {PROVIDERS[ai_provider].label}"
            + ("" if is_configured(settings, ai_provider) else " (no API key)"),
            done=is_configured(settings, ai_provider),
        )
    )
    return items


async def build_project(
    settings: Settings, db: Database, config: AiConfig, key: str
) -> Project:
    repo = config.project_repos[key]
    repo_exists = Path(repo).is_dir()
    host = await hosting.resolve(settings, db, key, repo)
    tests = key in tester.ConfigStore(db).projects()
    jira_on = is_jira_key(key)
    effective = resolve_provider_id(config, key)
    return Project(
        key=key,
        name=config.project_names.get(key) or key,
        repo_path=repo,
        repo_exists=repo_exists,
        jira=jira_on,
        host=host,
        jira_connected=settings.jira_configured,
        gitlab_connected=settings.gitlab_configured,
        github_connected=settings.github_configured,
        test_apps_configured=tests,
        ai_provider=config.project_providers.get(key),
        effective_ai_provider=effective,
        status=_status(settings, jira_on, repo_exists, host, tests, effective),
    )


def project_cards(
    cards: list[jira.Card],
    key: str,
    config: AiConfig,
    states: dict[str, dict[str, str]],
) -> list[ProjectCard]:
    """The cards whose key prefix is this project, with their latest step states."""
    return [
        ProjectCard(
            key=c.key,
            summary=c.summary,
            status=c.status,
            source=c.source,
            url=c.url,
            eligible=config.is_eligible(c.status, c.source),
            plan_state=states["plan"].get(c.key),
            implementation_state=states["implementation"].get(c.key),
            review_state=states["review"].get(c.key),
            test_state=states["test"].get(c.key),
        )
        for c in cards
        if c.project == key
    ]
