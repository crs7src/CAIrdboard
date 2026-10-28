from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import (
    feedback,
    implementer,
    planner,
    reviewer,
    tester,
)
from app.ai_config import load_ai_config
from app.config import (
    Settings,
)
from app.db import Approvals
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _repo_for_key,
    _states,
    _test_store,
    _valid_key,
)
from app.routes.cards import _load_card
from app.routes.feedback import _check_feedback_idle, _start_feedback

router = APIRouter()


@router.get("/api/tests")
def test_states(settings: SettingsDep) -> dict[str, str]:
    return _states(_test_store(settings), tester.recover_stale)


class StartTestBody(BaseModel):
    use_ai: bool = False


class TestConfigBody(BaseModel):
    __test__ = False

    apps: Annotated[list[tester.AppSpec], Field(min_length=1)]

    @field_validator("apps")
    @classmethod
    def unique(cls, v: list[tester.AppSpec]) -> list[tester.AppSpec]:
        return tester._unique_names(v)


class TestProblemBody(BaseModel):
    __test__ = False

    message: str

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Describe the problem")
        return v[:4000]


async def _test_context(settings: Settings, key: str):
    """Everything a test run needs, or an HTTP error if the card is not ready."""
    impl = implementer.ImplementationStore(_db(settings)).latest(key)
    if impl is None or impl.state != "completed" or not impl.branch:
        raise HTTPException(409, "The card has no completed implementation to test")
    review = reviewer.ReviewStore(_db(settings)).latest(key)
    if review is None or review.state != "clean":
        raise HTTPException(409, "The review must be clean before testing")
    plan = planner.PlanStore(_db(settings)).latest(key)
    if plan is None or not plan.plan:
        raise HTTPException(409, "The card has no plan")
    card = await _load_card(settings, key)
    return impl, review, plan, card, _repo_for_key(settings, key)


def _check_test_free(key: str, repo: str, previous, stoppable: bool) -> None:
    """409 if the card or repo is busy. A running test app of this card may be
    replaced when `stoppable`."""
    own_app = key in tester.APPS
    replaceable = stoppable and own_app
    other_busy = (
        key in implementer.ACTIVE or key in reviewer.ACTIVE or key in feedback.ACTIVE
    )
    own_busy = (key in tester.ACTIVE and not replaceable) or (
        previous is not None
        and (
            previous.state == "preparing"
            or (previous.state == "running" and not stoppable)
        )
    )
    if other_busy or own_busy:
        raise HTTPException(409, "This card is already being worked on")
    if repo in implementer.ACTIVE_REPOS and not replaceable:
        raise HTTPException(
            409,
            "Another run or a running test app is using this repo. Wait or stop it first.",
        )


@router.post("/api/cards/{key}/test", status_code=202)
async def start_test(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
    body: StartTestBody | None = None,
) -> tester.TestRun:
    """Run the reviewed branch for manual testing.

    Uses only the project's configured settings (no AI involved), unless `use_ai` is
    set, in which case an AI works out how to run it (and its result is saved).
    """
    key = _valid_key(key)
    impl, review, plan, card, repo = await _test_context(settings, key)
    store = _test_store(settings)
    previous = tester.recover_stale(store, store.latest(key))
    _check_test_free(key, repo, previous, stoppable=False)

    configs = tester.ConfigStore(_db(settings))
    use_ai = bool(body and body.use_ai)
    saved = None if use_ai else configs.load(tester.project_of(key))
    if not use_ai and saved is None:
        raise HTTPException(
            409,
            "No start settings are configured for this project. Set them under "
            "Settings > Test apps, or use AI start.",
        )
    run = store.create(key, impl, review.version, "saved" if saved else "ai")
    tester.ACTIVE.add(key)
    implementer.ACTIVE_REPOS.add(repo)
    background.add_task(
        tester.run_test,
        store,
        run,
        impl,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.test_timeout_seconds,
        settings.test_ready_timeout_seconds,
        runner,
        configs=configs,
        saved=saved.apps if saved else None,
        previous=previous,
    )
    return run


@router.post("/api/cards/{key}/test/problem", status_code=202)
async def report_test_problem(
    key: str,
    body: TestProblemBody,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> tester.TestRun:
    """Tell an AI what is not running right; it fixes the run settings and the apps restart."""
    key = _valid_key(key)
    impl, review, plan, card, repo = await _test_context(settings, key)
    store = _test_store(settings)
    previous = tester.recover_stale(store, store.latest(key))
    if previous is None:
        raise HTTPException(409, "Start the test before reporting a problem")
    _check_test_free(key, repo, previous, stoppable=True)
    if key in tester.APPS:
        await tester.stop_app(store, key)

    configs = tester.ConfigStore(_db(settings))
    saved = configs.load(tester.project_of(key))
    run = store.create(key, impl, review.version, "feedback", body.message)
    tester.ACTIVE.add(key)
    implementer.ACTIVE_REPOS.add(repo)
    background.add_task(
        tester.run_test,
        store,
        run,
        impl,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.test_timeout_seconds,
        settings.test_ready_timeout_seconds,
        runner,
        configs=configs,
        saved=saved.apps if saved else None,
        problem=body.message,
        previous=previous,
    )
    return run


@router.post("/api/cards/{key}/test/feedback", status_code=202)
async def send_test_feedback(
    key: str,
    body: TestProblemBody,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> feedback.FeedbackRun:
    """Hand issues found in manual testing to the AI that fixes review comments."""
    key = _valid_key(key)
    impl, _review, plan, card, repo = await _test_context(settings, key)
    test_store = _test_store(settings)
    previous = tester.recover_stale(test_store, test_store.latest(key))
    _check_test_free(key, repo, previous, stoppable=True)
    store = feedback.FeedbackStore(_db(settings))
    _check_feedback_idle(store, key)
    if key in tester.APPS:
        await tester.stop_app(test_store, key)
    store.add(key, feedback.CommentInput(text=body.message, origin="testing"))
    return _start_feedback(settings, runner, background, store, impl, plan, card, repo)


class ApprovalState(BaseModel):
    approved: bool
    approved_at: str | None = None


def _approval(settings: Settings, key: str) -> ApprovalState:
    at = Approvals(_db(settings)).get(key)
    return ApprovalState(approved=at is not None, approved_at=at)


@router.get("/api/test-approvals")
def list_test_approvals(settings: SettingsDep) -> list[str]:
    """Cards whose manual test is approved (a Home page check)."""
    return Approvals(_db(settings)).keys()


@router.get("/api/cards/{key}/test/approval")
def get_test_approval(key: str, settings: SettingsDep) -> ApprovalState:
    return _approval(settings, _valid_key(key))


@router.put("/api/cards/{key}/test/approval")
def approve_test(key: str, settings: SettingsDep) -> ApprovalState:
    """Approve the card's manual test. Changing the branch later withdraws it."""
    key = _valid_key(key)
    if _test_store(settings).latest(key) is None:
        raise HTTPException(409, "The card has not been manually tested yet")
    Approvals(_db(settings)).approve(key)
    return _approval(settings, key)


@router.delete("/api/cards/{key}/test/approval")
def unapprove_test(key: str, settings: SettingsDep) -> ApprovalState:
    key = _valid_key(key)
    Approvals(_db(settings)).clear(key)
    return _approval(settings, key)


@router.get("/api/test-configs")
def list_test_configs(settings: SettingsDep) -> list[str]:
    """Projects that have start settings, so the UI can enable the Test step."""
    return tester.ConfigStore(_db(settings)).projects()


def _project_repo(settings: Settings, project: str) -> str:
    if not tester.PROJECT_RE.match(project):
        raise HTTPException(404, "Unknown project")
    repo = load_ai_config(settings.ai_config_file).repo_for(project)
    if repo is None or not Path(repo).is_dir():
        raise HTTPException(404, "No valid repo is configured for this project")
    return repo


@router.get("/api/test-configs/{project}")
def get_project_test_config(project: str, settings: SettingsDep) -> tester.SavedConfig:
    _project_repo(settings, project)
    config = tester.ConfigStore(_db(settings)).load(project)
    if config is None:
        raise HTTPException(404, "No saved test settings for this project")
    return config


@router.put("/api/test-configs/{project}")
def put_project_test_config(
    project: str, body: TestConfigBody, settings: SettingsDep
) -> tester.SavedConfig:
    """Set how the project's apps are started for manual testing."""
    repo = _project_repo(settings, project)
    for spec in body.apps:
        try:
            tester.resolve_workdir(repo, spec.workdir)
        except tester.TesterError as e:
            raise HTTPException(422, str(e)) from e
    return tester.ConfigStore(_db(settings)).save(project, body.apps, "settings")


@router.delete("/api/test-configs/{project}", status_code=204)
def delete_project_test_config(project: str, settings: SettingsDep) -> None:
    _project_repo(settings, project)
    tester.ConfigStore(_db(settings)).delete(project)


@router.get("/api/cards/{key}/test/config")
def get_test_config(key: str, settings: SettingsDep) -> tester.SavedConfig:
    key = _valid_key(key)
    config = tester.ConfigStore(_db(settings)).load(tester.project_of(key))
    if config is None:
        raise HTTPException(404, "No saved test settings for this project")
    return config


@router.delete("/api/cards/{key}/test/config", status_code=204)
def forget_test_config(key: str, settings: SettingsDep) -> None:
    key = _valid_key(key)
    tester.ConfigStore(_db(settings)).delete(tester.project_of(key))


@router.get("/api/cards/{key}/test")
def get_test(key: str, settings: SettingsDep) -> tester.TestRun:
    key = _valid_key(key)
    store = _test_store(settings)
    run = tester.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No test run exists for this card")
    return run


@router.delete("/api/cards/{key}/test")
async def stop_test(key: str, settings: SettingsDep) -> tester.TestRun:
    """Stop the running test app and free the repo."""
    key = _valid_key(key)
    store = _test_store(settings)
    run = await tester.stop_app(store, key)
    if run is None:
        raise HTTPException(404, "No test run exists for this card")
    return tester.recover_stale(store, run) or run
