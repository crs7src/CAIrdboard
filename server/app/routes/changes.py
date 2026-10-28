from fastapi import APIRouter, HTTPException

from app import (
    changes,
    implementer,
)
from app.deps import (
    RunnerDep,
    SettingsDep,
    _db,
    _repo_for_key,
    _valid_key,
)

router = APIRouter()


@router.get("/api/cards/{key}/changes")
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
