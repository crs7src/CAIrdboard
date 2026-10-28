from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, field_validator

from app import (
    feedback,
    implementer,
    planner,
    reviewer,
)
from app.config import (
    Settings,
)
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _repo_for_key,
    _valid_key,
)
from app.routes.cards import _load_card
from app.routes.implementations import _feedback_then_review

router = APIRouter()


class FeedbackData(BaseModel):
    comments: list[feedback.FeedbackComment]
    run: feedback.FeedbackRun | None


def _feedback_data(store: feedback.FeedbackStore, key: str) -> FeedbackData:
    return FeedbackData(
        comments=store.comments(key),
        run=feedback.recover_stale(store, store.latest(key)),
    )


@router.get("/api/cards/{key}/feedback")
def get_feedback(key: str, settings: SettingsDep) -> FeedbackData:
    key = _valid_key(key)
    return _feedback_data(feedback.FeedbackStore(_db(settings)), key)


@router.post("/api/cards/{key}/feedback/comments", status_code=201)
def add_feedback_comment(
    key: str, body: feedback.CommentInput, settings: SettingsDep
) -> feedback.FeedbackComment:
    key = _valid_key(key)
    return feedback.FeedbackStore(_db(settings)).add(key, body)


class CommentEdit(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A comment cannot be empty")
        return v.strip()


@router.put("/api/cards/{key}/feedback/comments/{comment_id}")
def edit_feedback_comment(
    key: str, comment_id: str, body: CommentEdit, settings: SettingsDep
) -> feedback.FeedbackComment:
    key = _valid_key(key)
    comment = feedback.FeedbackStore(_db(settings)).edit(key, comment_id, body.text)
    if comment is None:
        raise HTTPException(404, "No pending comment with that id")
    return comment


@router.delete("/api/cards/{key}/feedback/comments/{comment_id}", status_code=204)
def delete_feedback_comment(key: str, comment_id: str, settings: SettingsDep) -> None:
    key = _valid_key(key)
    if not feedback.FeedbackStore(_db(settings)).delete(key, comment_id):
        raise HTTPException(404, "No pending comment with that id")


@router.post("/api/cards/{key}/feedback/submit", status_code=202)
async def submit_feedback(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> feedback.FeedbackRun:
    """Hand the pending review comments to a fresh AI session that makes the edits."""
    key = _valid_key(key)
    impl = implementer.ImplementationStore(_db(settings)).latest(key)
    if impl is None or impl.state != "completed" or not impl.branch:
        raise HTTPException(409, "The card has no completed implementation to change")
    plan = planner.PlanStore(_db(settings)).latest(key)
    if plan is None or not plan.plan:
        raise HTTPException(409, "The card has no plan")
    store = feedback.FeedbackStore(_db(settings))
    if not any(c.status == "pending" for c in store.comments(key)):
        raise HTTPException(409, "Add at least one comment first")
    card = await _load_card(settings, key)
    repo = _repo_for_key(settings, key)
    return _start_feedback(settings, runner, background, store, impl, plan, card, repo)


def _check_feedback_idle(store: feedback.FeedbackStore, key: str) -> None:
    previous = feedback.recover_stale(store, store.latest(key))
    if (
        key in feedback.ACTIVE
        or key in reviewer.ACTIVE
        or key in implementer.ACTIVE
        or (previous and previous.state == "running")
    ):
        raise HTTPException(409, "This card is already being worked on")


def _start_feedback(
    settings: Settings,
    runner,
    background: BackgroundTasks,
    store: feedback.FeedbackStore,
    impl,
    plan,
    card,
    repo: str,
) -> feedback.FeedbackRun:
    """Check the card and repo are free, then start a run on the pending comments."""
    key = card.key
    _check_feedback_idle(store, key)
    if repo in implementer.ACTIVE_REPOS:
        raise HTTPException(
            409, "Another run is in progress in this repo. Wait for it to finish."
        )

    run = store.create(key, impl)
    feedback.ACTIVE.add(key)
    implementer.ACTIVE_REPOS.add(repo)
    background.add_task(
        _feedback_then_review,
        settings,
        runner,
        store,
        run,
        impl,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.feedback_timeout_seconds,
        runner,
    )
    return run
