import asyncio
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app import (
    changes,
    feedback,
    github,
    gitlab,
    hosting,
    implementer,
    jira,
    merge_request,
    planner,
    remotes,
    reviewer,
    skills,
    tester,
)
from app.ai_config import AiConfig, load_ai_config, save_ai_config
from app.config import (
    GITHUB_FIELDS,
    GITLAB_FIELDS,
    Settings,
    get_settings,
    save_credentials,
)
from app.db import CARD_KEY_RE, Approvals, Database
from app.legacy_import import import_legacy_files
from app.remotes import HostError, HostProject


def _db(settings: Settings) -> Database:
    return Database.at(settings.db_file)


def _test_store(settings: Settings) -> tester.TestStore:
    return tester.TestStore(_db(settings), settings.test_runs_dir)


def _states(store, recover) -> dict[str, str]:
    """Latest state of every card that has a run in the store."""
    states: dict[str, str] = {}
    for key in store.card_keys():
        latest = recover(store, store.latest(key))
        if latest:
            states[key] = latest.state
    return states


@asynccontextmanager
async def lifespan(_: FastAPI):
    import_legacy_files(get_settings())
    yield
    # Apps started for manual testing must not outlive the server.
    await tester.stop_all(_test_store(get_settings()))


app = FastAPI(title="AI Card Board", lifespan=lifespan)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_runner():
    return planner.run_command


RunnerDep = Annotated[object, Depends(get_runner)]


class CredentialsUpdate(BaseModel):
    base_url: str | None = None
    email: str | None = None
    token: str | None = None

    @field_validator("base_url", "email", "token")
    @classmethod
    def not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Must start with http:// or https://")
        return v.rstrip("/")


@app.get("/api/jira/status")
async def jira_status(settings: SettingsDep) -> dict:
    status = {
        "configured": settings.jira_configured,
        "connected": False,
        "user": None,
        "base_url": settings.jira_base_url,
        "email": settings.jira_email,
    }
    if not settings.jira_configured:
        return status
    try:
        status["user"] = await jira.fetch_current_user(settings)
        status["connected"] = True
    except jira.JiraError:
        pass
    return status


@app.put("/api/jira/credentials")
async def update_credentials(body: CredentialsUpdate, settings: SettingsDep) -> dict:
    """Update the stored Jira credentials; omitted fields keep their current value.

    The merged result is verified against Jira before anything is saved.
    """
    updates = {
        "jira_base_url": body.base_url,
        "jira_email": body.email,
        "jira_api_token": body.token,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise HTTPException(422, "Provide at least one of base_url, email, token")
    candidate = settings.model_copy(update=updates)
    if not candidate.jira_configured:
        raise HTTPException(422, "Site URL, email and token are all required")
    try:
        user = await jira.fetch_current_user(candidate)
    except jira.JiraError as e:
        raise HTTPException(400, f"Jira did not accept these credentials: {e}") from e
    save_credentials(settings.jira_credentials_file, updates)
    return {"connected": True, "user": user}


def _require_jira(settings: Settings) -> None:
    if not settings.jira_configured:
        raise HTTPException(
            503, "Jira is not configured. Add your credentials in Settings."
        )


def _valid_key(key: str) -> str:
    if not CARD_KEY_RE.match(key):
        raise HTTPException(404, "Card not found")
    return key


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


@app.get("/api/cards")
async def cards(settings: SettingsDep, response: Response) -> list[jira.Card]:
    """Jira and GitHub cards. If one source fails while another works, its error is
    reported in the X-Card-Warnings header instead of failing the whole list."""
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
    if errors:
        response.headers["X-Card-Warnings"] = "; ".join(errors)
    return found


@app.get("/api/cards/{key}")
async def card_detail(key: str, settings: SettingsDep) -> CardDetail:
    card = await _load_card(settings, _valid_key(key))
    config = load_ai_config(settings.ai_config_file)
    return CardDetail(
        **card.model_dump(),
        eligible=config.is_eligible(card.status, card.source),
        repo_configured=config.repo_for(card.project) is not None,
    )


@app.get("/api/ai-config")
def get_ai_config(settings: SettingsDep) -> AiConfig:
    return load_ai_config(settings.ai_config_file)


@app.put("/api/ai-config")
def put_ai_config(config: AiConfig, settings: SettingsDep) -> AiConfig:
    save_ai_config(settings.ai_config_file, config)
    return config


class SkillInfo(BaseModel):
    step: str
    content: str
    default_content: str
    customized: bool


class SkillUpdate(BaseModel):
    content: str


def skill_info(step: str) -> SkillInfo:
    try:
        default = skills.read_default(step)
        override = skills.read_override(step)
    except skills.SkillError as e:
        raise HTTPException(500, str(e)) from e
    return SkillInfo(
        step=step,
        content=default if override is None else override,
        default_content=default,
        customized=override is not None,
    )


def check_step(step: str) -> None:
    if step not in skills.STEPS:
        raise HTTPException(404, f"Unknown step '{step}'")


@app.get("/api/skills")
def list_skills() -> list[SkillInfo]:
    return [skill_info(step) for step in skills.STEPS]


@app.put("/api/skills/{step}")
def put_skill(step: str, body: SkillUpdate) -> SkillInfo:
    check_step(step)
    try:
        skills.save_override(step, body.content)
    except skills.SkillError as e:
        raise HTTPException(422, str(e)) from e
    return skill_info(step)


@app.delete("/api/skills/{step}")
def reset_skill(step: str) -> SkillInfo:
    """Remove the user's override so the bundled default is used again."""
    check_step(step)
    skills.delete_override(step)
    return skill_info(step)


class DirEntry(BaseModel):
    name: str
    is_git: bool


class DirListing(BaseModel):
    path: str
    parent: str | None
    dirs: list[DirEntry]


@app.get("/api/fs/dirs")
def list_dirs(path: str | None = None) -> DirListing:
    """List sub-folders (never files) of a directory, for the repo picker."""
    target = Path(path).expanduser() if path else Path.home()
    if not target.is_absolute() or not target.is_dir():
        raise HTTPException(404, "Folder not found")
    target = target.resolve()
    dirs: list[DirEntry] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            dirs.append(DirEntry(name=child.name, is_git=(child / ".git").exists()))
    except PermissionError:
        raise HTTPException(403, "Permission denied") from None
    parent = str(target.parent) if target.parent != target else None
    return DirListing(path=str(target), parent=parent, dirs=dirs)


@app.get("/api/plans")
def plan_states(settings: SettingsDep) -> dict[str, str]:
    """Latest plan state for every card that has one."""
    return _states(planner.PlanStore(_db(settings)), planner.recover_stale)


@app.get("/api/implementations")
def implementation_states(settings: SettingsDep) -> dict[str, str]:
    """Latest implementation state for every card that has one."""
    return _states(
        implementer.ImplementationStore(_db(settings)), implementer.recover_stale
    )


class PlanRequest(BaseModel):
    feedback: str | None = None

    @field_validator("feedback")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


@app.post("/api/cards/{key}/plan", status_code=202)
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


@app.get("/api/cards/{key}/plan")
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


@app.post("/api/cards/{key}/plan/approve")
def approve_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "approved")


@app.post("/api/cards/{key}/plan/reject")
def reject_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "rejected")


def _repo_for_key(settings: Settings, key: str) -> str:
    config = load_ai_config(settings.ai_config_file)
    repo = config.repo_for(key.split("-")[0])
    if repo is None or not Path(repo).is_dir():
        raise HTTPException(422, "No valid repo is configured for this card's project")
    return repo


@app.post("/api/cards/{key}/implementation", status_code=202)
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
        implementer.run_implementation,
        store,
        run,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.implement_timeout_seconds,
        runner,
    )
    return run


@app.get("/api/cards/{key}/implementation")
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


@app.get("/api/reviews")
def review_states(settings: SettingsDep) -> dict[str, str]:
    """Latest review state for every card that has one."""
    return _states(reviewer.ReviewStore(_db(settings)), reviewer.recover_stale)


@app.post("/api/cards/{key}/review", status_code=202)
async def start_review(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
) -> reviewer.Review:
    """Review the completed implementation in a fresh AI session; it may commit fixes."""
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
    background.add_task(
        reviewer.run_review,
        store,
        run,
        impl,
        card,
        plan.plan,
        repo,
        settings.copilot_command,
        settings.review_timeout_seconds,
        runner,
    )
    return run


@app.get("/api/cards/{key}/review")
async def get_review(key: str, settings: SettingsDep) -> reviewer.Review:
    key = _valid_key(key)
    store = reviewer.ReviewStore(_db(settings))
    run = reviewer.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No review exists for this card")
    return run


class FeedbackData(BaseModel):
    comments: list[feedback.FeedbackComment]
    run: feedback.FeedbackRun | None


def _feedback_data(store: feedback.FeedbackStore, key: str) -> FeedbackData:
    return FeedbackData(
        comments=store.comments(key),
        run=feedback.recover_stale(store, store.latest(key)),
    )


@app.get("/api/cards/{key}/feedback")
def get_feedback(key: str, settings: SettingsDep) -> FeedbackData:
    key = _valid_key(key)
    return _feedback_data(feedback.FeedbackStore(_db(settings)), key)


@app.post("/api/cards/{key}/feedback/comments", status_code=201)
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


@app.put("/api/cards/{key}/feedback/comments/{comment_id}")
def edit_feedback_comment(
    key: str, comment_id: str, body: CommentEdit, settings: SettingsDep
) -> feedback.FeedbackComment:
    key = _valid_key(key)
    comment = feedback.FeedbackStore(_db(settings)).edit(key, comment_id, body.text)
    if comment is None:
        raise HTTPException(404, "No pending comment with that id")
    return comment


@app.delete("/api/cards/{key}/feedback/comments/{comment_id}", status_code=204)
def delete_feedback_comment(key: str, comment_id: str, settings: SettingsDep) -> None:
    key = _valid_key(key)
    if not feedback.FeedbackStore(_db(settings)).delete(key, comment_id):
        raise HTTPException(404, "No pending comment with that id")


@app.post("/api/cards/{key}/feedback/submit", status_code=202)
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
        feedback.run_feedback,
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


@app.get("/api/tests")
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


@app.post("/api/cards/{key}/test", status_code=202)
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


@app.post("/api/cards/{key}/test/problem", status_code=202)
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


@app.post("/api/cards/{key}/test/feedback", status_code=202)
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


@app.get("/api/test-approvals")
def list_test_approvals(settings: SettingsDep) -> list[str]:
    """Cards whose manual test is approved (a Home page check)."""
    return Approvals(_db(settings)).keys()


@app.get("/api/cards/{key}/test/approval")
def get_test_approval(key: str, settings: SettingsDep) -> ApprovalState:
    return _approval(settings, _valid_key(key))


@app.put("/api/cards/{key}/test/approval")
def approve_test(key: str, settings: SettingsDep) -> ApprovalState:
    """Approve the card's manual test. Changing the branch later withdraws it."""
    key = _valid_key(key)
    if _test_store(settings).latest(key) is None:
        raise HTTPException(409, "The card has not been manually tested yet")
    Approvals(_db(settings)).approve(key)
    return _approval(settings, key)


@app.delete("/api/cards/{key}/test/approval")
def unapprove_test(key: str, settings: SettingsDep) -> ApprovalState:
    key = _valid_key(key)
    Approvals(_db(settings)).clear(key)
    return _approval(settings, key)


@app.get("/api/test-configs")
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


@app.get("/api/test-configs/{project}")
def get_project_test_config(project: str, settings: SettingsDep) -> tester.SavedConfig:
    _project_repo(settings, project)
    config = tester.ConfigStore(_db(settings)).load(project)
    if config is None:
        raise HTTPException(404, "No saved test settings for this project")
    return config


@app.put("/api/test-configs/{project}")
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


@app.delete("/api/test-configs/{project}", status_code=204)
def delete_project_test_config(project: str, settings: SettingsDep) -> None:
    _project_repo(settings, project)
    tester.ConfigStore(_db(settings)).delete(project)


@app.get("/api/cards/{key}/test/config")
def get_test_config(key: str, settings: SettingsDep) -> tester.SavedConfig:
    key = _valid_key(key)
    config = tester.ConfigStore(_db(settings)).load(tester.project_of(key))
    if config is None:
        raise HTTPException(404, "No saved test settings for this project")
    return config


@app.delete("/api/cards/{key}/test/config", status_code=204)
def forget_test_config(key: str, settings: SettingsDep) -> None:
    key = _valid_key(key)
    tester.ConfigStore(_db(settings)).delete(tester.project_of(key))


@app.get("/api/cards/{key}/test")
def get_test(key: str, settings: SettingsDep) -> tester.TestRun:
    key = _valid_key(key)
    store = _test_store(settings)
    run = tester.recover_stale(store, store.latest(key))
    if run is None:
        raise HTTPException(404, "No test run exists for this card")
    return run


@app.delete("/api/cards/{key}/test")
async def stop_test(key: str, settings: SettingsDep) -> tester.TestRun:
    """Stop the running test app and free the repo."""
    key = _valid_key(key)
    store = _test_store(settings)
    run = await tester.stop_app(store, key)
    if run is None:
        raise HTTPException(404, "No test run exists for this card")
    return tester.recover_stale(store, run) or run


@app.get("/api/cards/{key}/changes")
async def get_changes(
    key: str, settings: SettingsDep, runner: RunnerDep, commit: str | None = None
) -> changes.Changes:
    """File-by-file diff of the card's branch, for manual review."""
    key = _valid_key(key)
    impl = implementer.ImplementationStore(_db(settings)).latest(key)
    if impl is None or not impl.branch or not impl.base_commit:
        raise HTTPException(404, "No implementation branch exists for this card")
    repo = _repo_for_key(settings, key)
    try:
        return await changes.load_changes(runner, repo, impl, commit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except implementer.ImplementationError as e:
        raise HTTPException(500, str(e)) from None


class HostCredentialsUpdate(BaseModel):
    url: str | None = None
    token: str | None = None

    @field_validator("url", "token")
    @classmethod
    def not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def valid_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Must start with http:// or https://")
        return v.rstrip("/")


class RepoHostBody(BaseModel):
    provider: hosting.Provider
    path: str

    @field_validator("path")
    @classmethod
    def clean_path(cls, v: str) -> str:
        return v.strip().strip("/").removesuffix(".git")

    @model_validator(mode="after")
    def valid_path(self) -> RepoHostBody:
        if self.provider == "github":
            if not remotes.REPO_PATH_RE.match(self.path):
                raise ValueError("Use the repository path, like owner/repo")
        elif not remotes.PROJECT_PATH_RE.match(self.path):
            raise ValueError("Use the project path, like group/subgroup/project")
        return self


async def _host_status(
    settings: Settings, provider: hosting.Provider, fetch_user, error
) -> dict:
    url = settings.gitlab_url if provider == "gitlab" else settings.github_url
    is_configured = hosting.configured(settings, provider)
    status = {"configured": is_configured, "connected": False, "user": None, "url": url}
    if not is_configured:
        return status
    try:
        status["user"] = await fetch_user(settings)
        status["connected"] = True
    except error:
        pass
    return status


async def _update_host_credentials(
    body: HostCredentialsUpdate,
    settings: Settings,
    provider: hosting.Provider,
    fetch_user,
) -> dict:
    """Verify the merged credentials against the host, then save them."""
    label = hosting.LABELS[provider]
    prefix = provider
    fields = GITLAB_FIELDS if provider == "gitlab" else GITHUB_FIELDS
    file = (
        settings.gitlab_credentials_file
        if provider == "gitlab"
        else settings.github_credentials_file
    )
    updates = {f"{prefix}_url": body.url, f"{prefix}_token": body.token}
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise HTTPException(422, "Provide at least one of url, token")
    candidate = settings.model_copy(update=updates)
    if not hosting.configured(candidate, provider):
        raise HTTPException(422, f"{label} URL and token are both required")
    try:
        user = await fetch_user(candidate)
    except HostError as e:
        raise HTTPException(
            400, f"{label} did not accept these credentials: {e}"
        ) from e
    save_credentials(file, updates, fields)
    return {"connected": True, "user": user}


@app.get("/api/gitlab/status")
async def gitlab_status(settings: SettingsDep) -> dict:
    return await _host_status(
        settings, "gitlab", gitlab.fetch_current_user, gitlab.GitLabError
    )


@app.put("/api/gitlab/credentials")
async def update_gitlab_credentials(
    body: HostCredentialsUpdate, settings: SettingsDep
) -> dict:
    """Update the stored GitLab credentials; verified against GitLab before saving."""
    return await _update_host_credentials(
        body, settings, "gitlab", gitlab.fetch_current_user
    )


@app.get("/api/github/status")
async def github_status(settings: SettingsDep) -> dict:
    return await _host_status(
        settings, "github", github.fetch_current_user, github.GitHubError
    )


@app.put("/api/github/credentials")
async def update_github_credentials(
    body: HostCredentialsUpdate, settings: SettingsDep
) -> dict:
    """Update the stored GitHub credentials; verified against GitHub before saving."""
    return await _update_host_credentials(
        body, settings, "github", github.fetch_current_user
    )


async def _repo_host(settings: Settings, project: str, repo: str) -> hosting.RepoHost:
    return await hosting.resolve(settings, _db(settings), project, repo)


@app.get("/api/repo-hosts")
async def list_repo_hosts(settings: SettingsDep) -> list[hosting.RepoHost]:
    """Every Jira project with a repo, and the GitLab/GitHub project it maps to."""
    repos = load_ai_config(settings.ai_config_file).project_repos
    return [
        await _repo_host(settings, project, repo)
        for project, repo in sorted(repos.items())
    ]


@app.get("/api/repo-hosts/{project}")
async def get_repo_host(project: str, settings: SettingsDep) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    return await _repo_host(settings, project.upper(), repo)


@app.put("/api/repo-hosts/{project}")
async def put_repo_host(
    project: str, body: RepoHostBody, settings: SettingsDep
) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    project = project.upper()
    hosting.Mappings(_db(settings)).set(project, body.provider, body.path)
    return await _repo_host(settings, project, repo)


@app.delete("/api/repo-hosts/{project}")
async def delete_repo_host(project: str, settings: SettingsDep) -> hosting.RepoHost:
    repo = _project_repo(settings, project)
    project = project.upper()
    hosting.Mappings(_db(settings)).delete(project)
    return await _repo_host(settings, project, repo)


@app.get("/api/repo-hosts/{project}/check")
async def check_repo_host(project: str, settings: SettingsDep) -> HostProject:
    """Confirm the token can see the mapped project and report its default branch."""
    repo = _project_repo(settings, project)
    host = await _repo_host(settings, project.upper(), repo)
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
    try:
        return await hosting.fetch_project(settings, host.provider, host.path)
    except HostError as e:
        raise HTTPException(502, str(e)) from e


def _mr_repo(settings: Settings, key: str) -> str | None:
    repo = load_ai_config(settings.ai_config_file).repo_for(key.split("-")[0])
    return repo if repo and Path(repo).is_dir() else None


@app.get("/api/merge-requests")
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


@app.get("/api/cards/{key}/merge-request")
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


@app.post("/api/cards/{key}/merge-request", status_code=202)
async def create_merge_request(
    key: str,
    settings: SettingsDep,
    runner: RunnerDep,
    background: BackgroundTasks,
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

    run = store.create(key, impl, host.provider, host.path)
    merge_request.ACTIVE.add(key)
    background.add_task(
        merge_request.run_merge_request, store, run, impl, card, repo, settings, runner
    )
    return run
