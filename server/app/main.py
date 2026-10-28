from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.legacy_import import import_legacy_files
from app.deps import _test_store, get_runner
from app.routes import (
    ai_providers,
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    import_legacy_files(get_settings())
    yield
    # Apps started for manual testing must not outlive the server.
    await tester.stop_all(_test_store(get_settings()))


app = FastAPI(title="AI Card Board", lifespan=lifespan)

for module in (
    ai_providers,
    jira_auth,
    gitlab_auth,
    github_auth,
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
