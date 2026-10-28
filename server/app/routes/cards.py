import asyncio
from collections.abc import Awaitable

from fastapi import APIRouter, HTTPException, Response

from app import (
    github,
    jira,
    remotes,
)
from app.ai_config import load_ai_config, save_ai_config
from app.config import (
    Settings,
)
from app.deps import (
    SettingsDep,
    _db,
    _valid_key,
)
from app.remotes import HostError

router = APIRouter()


def _require_jira(settings: Settings) -> None:
    if not settings.jira_configured:
        raise HTTPException(
            503, "Jira is not configured. Add your credentials in Settings."
        )


async def _link_issue_repos(settings: Settings, cards: list[jira.Card]) -> None:
    """Map a GitHub issue's project to the local repo whose origin is that GitHub repo,
    so its plans can run there without a manual mapping."""
    config = load_ai_config(settings.ai_config_file)
    pending = {
        c.project: c.external_repo.lower()
        for c in cards
        if c.source == "github" and c.external_repo and not config.repo_for(c.project)
    }
    if not pending:
        return
    origins: dict[str, str | None] = {}
    for repo in dict.fromkeys(config.project_repos.values()):
        remote = await remotes.origin_remote(repo)
        origins[repo] = remote[1].lower() if remote else None
    changed = False
    for project, wanted in pending.items():
        repo = next((r for r, path in origins.items() if path == wanted), None)
        if repo:
            config.project_repos[project] = repo
            changed = True
    if changed:
        save_ai_config(settings.ai_config_file, config)


async def _load_card(settings: Settings, key: str) -> jira.Card:
    card = await _fetch_card(settings, key)
    await _link_issue_repos(settings, [card])
    return card


async def _fetch_card(settings: Settings, key: str) -> jira.Card:
    github_issue = github.is_issue_key(key)
    if github_issue and not settings.github_configured:
        raise HTTPException(
            503, "GitHub is not configured. Add your credentials in Settings."
        )
    if not github_issue:
        _require_jira(settings)
    try:
        if github_issue:
            return await github.fetch_issue_card(settings, _db(settings), key)
        return await jira.fetch_card(settings, key)
    except jira.CardNotFound as e:
        raise HTTPException(404, f"Card {key} not found") from e
    except (jira.JiraError, HostError) as e:
        raise HTTPException(502, str(e)) from e


class CardDetail(jira.Card):
    eligible: bool
    repo_configured: bool


async def _load_cards(settings: Settings) -> tuple[list[jira.Card], list[str]]:
    """Jira and GitHub cards plus the errors of sources that failed. Raises 503 when
    no source is configured and 502 when every configured source fails."""
    if not settings.jira_configured and not settings.github_configured:
        _require_jira(settings)
    sources: list[tuple[str, Awaitable[list[jira.Card]]]] = []
    if settings.jira_configured:
        sources.append(("Jira", jira.fetch_assigned_cards(settings)))
    if settings.github_configured:
        sources.append(
            ("GitHub", github.fetch_assigned_issues(settings, _db(settings)))
        )
    results = await asyncio.gather(
        *(coro for _, coro in sources), return_exceptions=True
    )
    found: list[jira.Card] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, list):
            found += result
        elif isinstance(result, jira.JiraError | HostError):
            errors.append(str(result))
        else:
            raise result
    if errors and len(errors) == len(results):
        raise HTTPException(502, "; ".join(errors))
    await _link_issue_repos(settings, found)
    return found, errors


@router.get("/api/cards")
async def cards(settings: SettingsDep, response: Response) -> list[jira.Card]:
    """Jira and GitHub cards. If one source fails while another works, its error is
    reported in the X-Card-Warnings header instead of failing the whole list."""
    found, errors = await _load_cards(settings)
    if errors:
        response.headers["X-Card-Warnings"] = "; ".join(errors)
    return found


@router.get("/api/cards/{key}")
async def card_detail(key: str, settings: SettingsDep) -> CardDetail:
    card = await _load_card(settings, _valid_key(key))
    config = load_ai_config(settings.ai_config_file)
    return CardDetail(
        **card.model_dump(),
        eligible=config.is_eligible(card.status, card.source),
        repo_configured=config.repo_for(card.project) is not None,
    )
