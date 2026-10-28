from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, field_validator

from app import (
    planner,
)
from app.ai_config import load_ai_config
from app.config import (
    Settings,
)
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _states,
    _valid_key,
)
from app.routes.cards import _load_card

router = APIRouter()


@router.get("/api/plans")
def plan_states(settings: SettingsDep) -> dict[str, str]:
    """Latest plan state for every card that has one."""
    return _states(planner.PlanStore(_db(settings)), planner.recover_stale)


class PlanRequest(BaseModel):
    feedback: str | None = None

    @field_validator("feedback")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


@router.post("/api/cards/{key}/plan", status_code=202)
async def create_plan(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
    body: PlanRequest | None = None,
) -> planner.Plan:
    """Start generating a plan. Optional feedback is used when regenerating."""
    key = _valid_key(key)
    card = await _load_card(settings, key)
    config = load_ai_config(settings.ai_config_file)
    if not config.is_eligible(card.status, card.source):
        raise HTTPException(
            409, f"Plans are not generated for cards in status '{card.status}'"
        )
    repo = config.repo_for(card.project)
    if repo is None:
        raise HTTPException(
            422,
            f"No repo is configured for project {card.project}. Add it in Settings.",
        )
    if not Path(repo).is_dir():
        raise HTTPException(422, f"Repo path for {card.project} does not exist: {repo}")

    store = planner.PlanStore(_db(settings))
    previous = planner.recover_stale(store, store.latest(key))
    if key in planner.ACTIVE or (previous and previous.state == "running"):
        raise HTTPException(409, "A plan is already being generated for this card")

    feedback = body.feedback if body else None
    plan = store.create(key, card.status, feedback)
    planner.ACTIVE.add(key)
    background.add_task(
        planner.generate,
        store,
        plan,
        card,
        previous,
        repo,
        settings.copilot_command,
        settings.plan_timeout_seconds,
        runner,
    )
    return plan


def _latest_plan(settings: Settings, key: str) -> planner.Plan:
    store = planner.PlanStore(_db(settings))
    plan = planner.recover_stale(store, store.latest(_valid_key(key)))
    if plan is None:
        raise HTTPException(404, "No plan exists for this card")
    return plan


@router.get("/api/cards/{key}/plan")
def get_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _latest_plan(settings, key)


def _decide(settings: Settings, key: str, state: planner.PlanState) -> planner.Plan:
    plan = _latest_plan(settings, key)
    if plan.state != "ready":
        raise HTTPException(
            409, f"Only a ready plan can be decided (it is {plan.state})"
        )
    plan.state = state
    return planner.PlanStore(_db(settings)).save(plan)


@router.post("/api/cards/{key}/plan/approve")
def approve_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "approved")


@router.post("/api/cards/{key}/plan/reject")
def reject_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "rejected")
