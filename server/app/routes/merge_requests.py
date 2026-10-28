from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from pydantic import BaseModel, field_validator

from app.core.ai_config import load_ai_config
from app.core.config import (
    Settings,
)
from app.core.db import Approvals
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _repo_for_key,
    _valid_key,
)
from app.integrations import hosting
from app.routes.cards import _load_card
from app.routes.repo_hosts import _repo_host
from app.stages import feedback, implementer, merge_request, reviewer, tester

router = APIRouter()


def _mr_repo(settings: Settings, key: str) -> str | None:
    repo = load_ai_config(settings.ai_config_file).repo_for(key.split("-")[0])
    return repo if repo and Path(repo).is_dir() else None


@router.get("/api/merge-requests")
async def merge_request_states(
    settings: SettingsDep, runner: RunnerDep
) -> dict[str, str]:
    """Latest merge request state per card; `outdated` means the branch moved on since."""
    store = merge_request.MergeRequestStore(_db(settings))
    states: dict[str, str] = {}
    for key in store.card_keys():
        run = merge_request.recover_stale(store, store.latest(key))
        if run is None:
            continue
        await merge_request.mark_outdated(runner, _mr_repo(settings, key), run)
        states[key] = "outdated" if run.outdated else run.state
    return states


@router.get("/api/cards/{key}/merge-request")
async def get_merge_request(
    key: str, settings: SettingsDep, runner: RunnerDep
) -> merge_request.MergeRequest:
    key = _valid_key(key)
    store = merge_request.MergeRequestStore(_db(settings))
    run = merge_request.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No merge request exists for this card")
    await merge_request.mark_outdated(runner, _mr_repo(settings, key), run)
    return run


class MergeRequestDefaults(BaseModel):
    title: str
    description: str


@router.get("/api/cards/{key}/merge-request/defaults")
async def merge_request_defaults(
    key: str, settings: SettingsDep, runner: RunnerDep
) -> MergeRequestDefaults:
    """The title and description a new merge request gets unless the user edits them."""
    key = _valid_key(key)
    impl = implementer.ImplementationStore(_db(settings)).latest(key)
    if impl is None or impl.state != "completed" or not impl.branch:
        raise HTTPException(409, "The card has no completed implementation")
    repo = _repo_for_key(settings, key)
    host = await _repo_host(settings, key.split("-")[0], repo)
    card = await _load_card(settings, key)
    description = await merge_request.build_description(
        runner,
        repo,
        impl,
        impl.branch,
        card,
        merge_request.closing_line(card, host.provider or "", host.path or ""),
    )
    return MergeRequestDefaults(
        title=merge_request.title_for(impl.branch), description=description
    )


class MergeRequestBody(BaseModel):
    title: str | None = None
    description: str | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("The title cannot be blank")
        return v.strip() if v is not None else None


@router.post("/api/cards/{key}/merge-request", status_code=202)
async def create_merge_request(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
    body: Annotated[MergeRequestBody | None, Body()] = None,
) -> merge_request.MergeRequest:
    """Push the approved branch to origin and open its merge request (or update it)."""
    key = _valid_key(key)
    impl = implementer.ImplementationStore(_db(settings)).latest(key)
    if impl is None or impl.state != "completed" or not impl.branch:
        raise HTTPException(409, "The card has no completed implementation")
    if Approvals(_db(settings)).get(key) is None:
        raise HTTPException(
            409, "Approve the manual test before creating a merge request"
        )
    repo = _repo_for_key(settings, key)
    host = await _repo_host(settings, key.split("-")[0], repo)
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
    card = await _load_card(settings, key)

    store = merge_request.MergeRequestStore(_db(settings))
    previous = merge_request.recover_stale(store, store.latest(key))
    if (
        key in merge_request.ACTIVE
        or key in implementer.ACTIVE
        or key in reviewer.ACTIVE
        or key in feedback.ACTIVE
        or key in tester.ACTIVE
        or (previous and previous.state == "running")
    ):
        raise HTTPException(409, "This card is already being worked on")

    run = store.create(
        key,
        impl,
        host.provider,
        host.path,
        title=body.title if body else None,
        description=body.description if body else None,
    )
    merge_request.ACTIVE.add(key)
    background.add_task(
        merge_request.run_merge_request, store, run, impl, card, repo, settings, runner
    )
    return run
