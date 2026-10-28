from fastapi import APIRouter

from app.core.db import Archive
from app.deps import SettingsDep, _db, _valid_key

router = APIRouter()


@router.get("/api/archive")
def list_archive(settings: SettingsDep) -> list[str]:
    """Keys of the archived cards (hidden from Home and the project views)."""
    return Archive(_db(settings)).keys()


@router.put("/api/cards/{key}/archive", status_code=204)
def archive_card(key: str, settings: SettingsDep) -> None:
    Archive(_db(settings)).add(_valid_key(key))


@router.delete("/api/cards/{key}/archive", status_code=204)
def unarchive_card(key: str, settings: SettingsDep) -> None:
    Archive(_db(settings)).remove(_valid_key(key))
