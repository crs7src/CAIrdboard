from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from app import jira, planner
from app.ai_config import AiConfig, load_ai_config, save_ai_config
from app.config import Settings, get_settings, save_credentials

app = FastAPI(title="AI Card Board")

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
    if not planner.CARD_KEY_RE.match(key):
        raise HTTPException(404, "Card not found")
    return key


async def _load_card(settings: Settings, key: str) -> jira.Card:
    _require_jira(settings)
    try:
        return await jira.fetch_card(settings, key)
    except jira.CardNotFound as e:
        raise HTTPException(404, f"Card {key} not found") from e
    except jira.JiraError as e:
        raise HTTPException(502, str(e)) from e


class CardDetail(jira.Card):
    eligible: bool
    repo_configured: bool


@app.get("/api/cards")
async def cards(settings: SettingsDep) -> list[jira.Card]:
    _require_jira(settings)
    try:
        return await jira.fetch_assigned_cards(settings)
    except jira.JiraError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/cards/{key}")
async def card_detail(key: str, settings: SettingsDep) -> CardDetail:
    card = await _load_card(settings, _valid_key(key))
    config = load_ai_config(settings.ai_config_file)
    return CardDetail(
        **card.model_dump(),
        eligible=config.is_eligible(card.status),
        repo_configured=config.repo_for(card.project) is not None,
    )


@app.get("/api/ai-config")
def get_ai_config(settings: SettingsDep) -> AiConfig:
    return load_ai_config(settings.ai_config_file)


@app.put("/api/ai-config")
def put_ai_config(config: AiConfig, settings: SettingsDep) -> AiConfig:
    save_ai_config(settings.ai_config_file, config)
    return config


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
    store = planner.PlanStore(settings.plans_dir)
    states: dict[str, str] = {}
    if settings.plans_dir.exists():
        for d in sorted(settings.plans_dir.iterdir()):
            if d.is_dir() and planner.CARD_KEY_RE.match(d.name):
                latest = planner.recover_stale(store, store.latest(d.name))
                if latest:
                    states[d.name] = latest.state
    return states


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
    if not config.is_eligible(card.status):
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

    store = planner.PlanStore(settings.plans_dir)
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
    store = planner.PlanStore(settings.plans_dir)
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
    return planner.PlanStore(settings.plans_dir).save(plan)


@app.post("/api/cards/{key}/plan/approve")
def approve_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "approved")


@app.post("/api/cards/{key}/plan/reject")
def reject_plan(key: str, settings: SettingsDep) -> planner.Plan:
    return _decide(settings, key, "rejected")
