from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import (
    Settings,
)
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _repo_for_key,
    _states,
    _valid_key,
    agent_provider_for,
)
from app.routes.cards import _load_card
from app.stages import implementer, planner, reviewer

router = APIRouter()


@router.get("/api/reviews")
def review_states(settings: SettingsDep) -> dict[str, str]:
    """Latest review state for every card that has one."""
    return _states(reviewer.ReviewStore(_db(settings)), reviewer.recover_stale)


async def _prepare_review(
    key: str, settings: Settings, runner: object
) -> tuple[reviewer.Review, tuple]:
    """Check a review can start, create the run and claim the card and repo.

    Returns the run and the arguments for ``reviewer.run_review``.
    """
    key = _valid_key(key)
    impl_store = implementer.ImplementationStore(_db(settings))
    impl = impl_store.latest(key)
    if impl is None or impl.state != "completed" or not impl.branch:
        raise HTTPException(409, "Only a completed implementation can be reviewed")
    plan = planner.PlanStore(_db(settings)).latest(key)
    if plan is None or not plan.plan:
        raise HTTPException(409, "The card has no plan to review against")
    card = await _load_card(settings, key)
    repo = _repo_for_key(settings, key)
    provider = agent_provider_for(settings, runner, card.project)

    store = reviewer.ReviewStore(_db(settings))
    previous = reviewer.recover_stale(store, store.latest(key))
    if (
        key in reviewer.ACTIVE
        or key in implementer.ACTIVE
        or (previous and previous.state == "running")
    ):
        raise HTTPException(409, "This card is already being worked on")
    if repo in implementer.ACTIVE_REPOS:
        raise HTTPException(
            409, "Another run is in progress in this repo. Wait for it to finish."
        )

    run = store.create(key, impl)
    reviewer.ACTIVE.add(key)
    implementer.ACTIVE_REPOS.add(repo)
    return run, (
        store,
        run,
        impl,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.review_timeout_seconds,
        runner,
        provider,
    )


@router.post("/api/cards/{key}/review", status_code=202)
async def start_review(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> reviewer.Review:
    """Review the completed implementation in a fresh AI session; it may commit fixes."""
    run, args = await _prepare_review(key, settings, runner)
    background.add_task(reviewer.run_review, *args)
    return run


@router.get("/api/cards/{key}/review")
async def get_review(key: str, settings: SettingsDep) -> reviewer.Review:
    key = _valid_key(key)
    store = reviewer.ReviewStore(_db(settings))
    run = reviewer.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No review exists for this card")
    return run
