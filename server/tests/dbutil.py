from app.core.config import Settings
from app.core.db import Database


def db() -> Database:
    """The per-test database that the app under test also uses (DB_FILE)."""
    return Database.at(Settings().db_file)
