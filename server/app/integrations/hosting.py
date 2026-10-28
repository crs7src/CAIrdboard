"""Which git host (GitLab or GitHub) and project each Jira project's repo lives on."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.core.config import Settings
from app.core.db import Database
from app.integrations import github, gitlab
from app.integrations.remotes import ChangeRequest, HostProject, origin_remote

Provider = Literal["gitlab", "github"]
PROVIDERS: tuple[Provider, ...] = ("gitlab", "github")
TABLES = {"gitlab": "gitlab_projects", "github": "github_projects"}
LABELS = {"gitlab": "GitLab", "github": "GitHub"}
NOUNS = {"gitlab": "merge request", "github": "pull request"}


class Target(BaseModel):
    provider: Provider
    path: str


class RepoHost(BaseModel):
    """The host project one Jira project's repo maps to."""

    project: str
    repo: str
    provider: Provider | None
    path: str | None
    source: Literal["override", "origin"] | None
    detected: Target | None


def configured(settings: Settings, provider: Provider) -> bool:
    return (
        settings.gitlab_configured
        if provider == "gitlab"
        else settings.github_configured
    )


class Mappings:
    """Per-Jira-project override of the host project (one provider per project)."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, project: str) -> Target | None:
        with self.db.connect() as conn:
            for provider, table in TABLES.items():
                row = conn.execute(
                    f"SELECT path FROM {table} WHERE project = ?",
                    (project,),
                ).fetchone()
                if row:
                    return Target(provider=provider, path=row[0])
        return None

    def set(self, project: str, provider: Provider, path: str) -> None:
        self.delete(project)
        with self.db.connect() as conn:
            conn.execute(
                f"INSERT INTO {TABLES[provider]} (project, path) VALUES (?, ?)",
                (project, path),
            )

    def delete(self, project: str) -> None:
        with self.db.connect() as conn:
            for table in TABLES.values():
                conn.execute(f"DELETE FROM {table} WHERE project = ?", (project,))


def _detect(settings: Settings, host: str) -> Provider | None:
    if host == github.web_host(settings.github_url):
        return "github"
    gitlab_host = (urlsplit(settings.gitlab_url).hostname or "").lower()
    # Before GitLab is set up, assume any other host is the GitLab one.
    if not gitlab_host or host == gitlab_host:
        return "gitlab"
    return None


async def resolve(
    settings: Settings, db: Database, project: str, repo: str
) -> RepoHost:
    detected = None
    remote = await origin_remote(repo)
    if remote:
        provider = _detect(settings, remote[0])
        if provider:
            detected = Target(provider=provider, path=remote[1])
    override = Mappings(db).get(project)
    target = override or detected
    return RepoHost(
        project=project,
        repo=repo,
        provider=target.provider if target else None,
        path=target.path if target else None,
        source=("override" if override else "origin") if target else None,
        detected=detected,
    )


async def find_open(
    settings: Settings, provider: Provider, path: str, branch: str
) -> ChangeRequest | None:
    if provider == "github":
        return await github.find_open_pull_request(settings, path, branch)
    return await gitlab.find_open_merge_request(settings, path, branch)


async def create(
    settings: Settings,
    provider: Provider,
    path: str,
    branch: str,
    target_branch: str,
    title: str,
    description: str,
) -> ChangeRequest:
    if provider == "github":
        return await github.create_pull_request(
            settings, path, branch, target_branch, title, description
        )
    return await gitlab.create_merge_request(
        settings, path, branch, target_branch, title, description
    )


async def fetch_project(
    settings: Settings, provider: Provider, path: str
) -> HostProject:
    if provider == "github":
        return await github.fetch_project(settings, path)
    return await gitlab.fetch_project(settings, path)
