from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.db import Resets, last_activity
from app.deps import RunnerDep, SettingsDep, _db, _repo_for_key, _test_store, _valid_key
from app.stages import reset

router = APIRouter()


class ResetRequest(BaseModel):
    delete_branch: bool = True


def reset_pending(settings, key: str, last_reopened_at: str | None) -> bool:
    """True when the card was reopened after its latest run, reset or dismissal."""
    if not last_reopened_at:
        return False
    db = _db(settings)
    seen = [s for s in (last_activity(db, key), Resets(db).get(key)) if s]
    return all(_ts(last_reopened_at) > _ts(s) for s in seen)


def _ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@router.post("/api/cards/{key}/reset")
async def reset_card(
    key: str, settings: SettingsDep, runner: RunnerDep, body: ResetRequest | None = None
) -> reset.ResetResult:
    """Delete the card's runs, comments and approval, and (by default) its local branch."""
    key = _valid_key(key)
    body = body or ResetRequest()
    repo = _repo_for_key(settings, key)
    try:
        return await reset.reset_card(
            runner, _db(settings), _test_store(settings), key, repo, body.delete_branch
        )
    except reset.ResetError as e:
        raise HTTPException(e.status, str(e)) from e


@router.put("/api/cards/{key}/reopen-prompt/dismiss", status_code=204)
def dismiss_reopen_prompt(key: str, settings: SettingsDep) -> None:
    Resets(_db(settings)).mark(_valid_key(key), "dismissed")
