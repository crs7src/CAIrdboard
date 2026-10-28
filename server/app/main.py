import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import JiraProjects
from app.core.legacy_import import import_legacy_files
from app.deps import _db, _test_store, get_runner
from app.integrations import jira
from app.routes import (
    ai_providers,
    archive,
    cards,
    changes,
    feedback,
    github_auth,
    gitlab_auth,
    implementations,
    jira_auth,
    merge_requests,
    plans,
    projects,
    repo_hosts,
    reviews,
    settings,
    tests,
)
from app.stages import tester

__all__ = ["app", "get_runner"]


log = logging.getLogger(__name__)


async def warm_jira_projects() -> None:
    """Learn the user's Jira project keys at startup so the New project form has
    suggestions. Errors are only logged."""
    try:
        settings = get_settings()
        if not settings.jira_configured:
            return
        cards = await jira.fetch_assigned_cards(settings)
        JiraProjects(_db(settings)).remember(c.project for c in cards)
    except Exception:
        log.exception("Could not load Jira project keys at startup")


@asynccontextmanager
async def lifespan(_: FastAPI):
    import_legacy_files(get_settings())
    warm_up = asyncio.create_task(warm_jira_projects())
    yield
    warm_up.cancel()
    # Apps started for manual testing must not outlive the server.
    await tester.stop_all(_test_store(get_settings()))


app = FastAPI(title="AI Card Board", lifespan=lifespan)

for module in (
    ai_providers,
    jira_auth,
    gitlab_auth,
    github_auth,
    archive,
    cards,
    plans,
    implementations,
    reviews,
    feedback,
    tests,
    changes,
    repo_hosts,
    projects,
    merge_requests,
    settings,
):
    app.include_router(module.router)
