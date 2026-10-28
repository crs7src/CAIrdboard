import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.ai_config import load_ai_config
from app.core.config import (
    Settings,
)
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _implementation_states,
    _repo_for_key,
    _valid_key,
)
from app.integrations import jira
from app.routes.cards import _load_card
from app.routes.reviews import _prepare_review
from app.stages import feedback, implementer, planner, reviewer

router = APIRouter()


@router.get("/api/implementations")
def implementation_states(settings: SettingsDep) -> dict[str, str]:
    """Latest implementation state for every card that has one."""
    return _implementation_states(settings)


@router.post("/api/cards/{key}/implementation", status_code=202)
async def start_implementation(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> implementer.Implementation:
    """Implement the approved plan on a new branch in the project's repo."""
    key = _valid_key(key)
    plan = planner.PlanStore(_db(settings)).latest(key)
    if plan is None or plan.state != "approved" or not plan.plan:
        raise HTTPException(409, "Only an approved plan can be implemented")
    card = await _load_card(settings, key)
    repo = _repo_for_key(settings, key)

    store = implementer.ImplementationStore(_db(settings))
    previous = implementer.recover_stale(store, store.latest(key))
    if key in implementer.ACTIVE or (previous and previous.state == "running"):
        raise HTTPException(409, "This card is already being implemented")
    if repo in implementer.ACTIVE_REPOS:
        raise HTTPException(
            409,
            "Another implementation is running in this repo. Wait for it to finish.",
        )

    run = store.create(key, plan.version)
    implementer.ACTIVE.add(key)
    implementer.ACTIVE_REPOS.add(repo)
    background.add_task(
        _implement_then_review,
        settings,
        runner,
        store,
        run,
        card,
        plan.plan,
        repo,
    )
    return run


async def _implement_then_review(
    settings: Settings,
    runner: object,
    store: implementer.ImplementationStore,
    run: implementer.Implementation,
    card: jira.Card,
    plan_text: str,
    repo: str,
) -> None:
    await implementer.run_implementation(
        store,
        run,
        card,
        plan_text,
        repo,
        settings.copilot_command,
        settings.implement_timeout_seconds,
        runner,
    )
    await _auto_review(settings, runner, run.card_key, run.version, store)


async def _auto_review(
    settings: Settings,
    runner: object,
    key: str,
    version: int,
    store: object,
    done_state: str = "completed",
) -> None:
    """Start a review after a run that changed code, if the setting is on.

    The run has released the card and repo by now. The setting is read here so
    a change made while the run was going is honoured.
    """
    try:
        latest = store.latest(key)
        if (
            latest is None
            or latest.version != version
            or latest.state != done_state
            or not load_ai_config(settings.ai_config_file).auto_review
        ):
            return
        _, args = await _prepare_review(key, settings, runner)
        await reviewer.run_review(*args)
    except Exception:
        logging.getLogger(__name__).warning(
            "Automatic review of %s was not started", key, exc_info=True
        )


async def _feedback_then_review(
    settings: Settings, runner: object, store: feedback.FeedbackStore, run, *args
) -> None:
    await feedback.run_feedback(store, run, *args)
    await _auto_review(settings, runner, run.card_key, run.version, store, "done")


@router.get("/api/cards/{key}/implementation")
async def get_implementation(
    key: str, settings: SettingsDep, runner: RunnerDep
) -> implementer.Implementation:
    key = _valid_key(key)
    store = implementer.ImplementationStore(_db(settings))
    run = implementer.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No implementation exists for this card")
    if run.state == "running" and run.base_commit:
        # Show commits as they land while the AI is still working.
        try:
            run.commits = await implementer.list_commits(
                runner, _repo_for_key(settings, key), run.base_commit
            )
        except implementer.ImplementationError, HTTPException:
            pass
    return run
