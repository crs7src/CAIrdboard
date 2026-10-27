"""One-time import of the JSON files used before the SQLite database existed.

Each kind is imported at most once (recorded in the meta table), so rows deleted later
are never resurrected. The old files are left untouched.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app import feedback, implementer, planner, reviewer, tester
from app.config import Settings
from app.db import CARD_KEY_RE, Database, put_run


def _json_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _card_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        d for d in sorted(root.iterdir()) if d.is_dir() and CARD_KEY_RE.match(d.name)
    ]


def _load[M: BaseModel](model: type[M], path: Path) -> M | None:
    try:
        return model.model_validate_json(path.read_text())
    except OSError, ValueError, ValidationError:
        return None


def _import_runs[M: BaseModel](
    db: Database, kind: str, model: type[M], root: Path, sub: str = ""
) -> int:
    count = 0
    for card_dir in _card_dirs(root):
        for path in _json_files(card_dir / sub if sub else card_dir):
            run = _load(model, path)
            if run is not None and getattr(run, "card_key", None) == card_dir.name:
                put_run(db, kind, run)
                count += 1
    return count


def _import_comments(db: Database, root: Path) -> int:
    count = 0
    for card_dir in _card_dirs(root):
        path = card_dir / "comments.json"
        try:
            raw = json.loads(path.read_text())
            comments = [feedback.FeedbackComment.model_validate(c) for c in raw]
        except OSError, ValueError, ValidationError:
            continue
        with db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO comments (card_key, id, data) VALUES (?, ?, ?)",
                [(card_dir.name, c.id, c.model_dump_json()) for c in comments],
            )
        count += len(comments)
    return count


def _import_configs(db: Database, root: Path) -> int:
    count = 0
    for path in _json_files(root):
        config = _load(tester.SavedConfig, path)
        if config is not None and tester.PROJECT_RE.match(config.project):
            with db.connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO test_configs (project, data) VALUES (?, ?)",
                    (config.project, config.model_dump_json()),
                )
            count += 1
    return count


def import_legacy_files(settings: Settings) -> dict[str, int]:
    """Import any not-yet-imported kind; returns how many rows each import added."""
    db = Database.at(settings.db_file)
    jobs = {
        "plan": lambda: _import_runs(db, "plan", planner.Plan, settings.plans_dir),
        "implementation": lambda: _import_runs(
            db,
            "implementation",
            implementer.Implementation,
            settings.implementations_dir,
        ),
        "review": lambda: _import_runs(
            db, "review", reviewer.Review, settings.reviews_dir
        ),
        "test": lambda: _import_runs(
            db, "test", tester.TestRun, settings.test_runs_dir
        ),
        "feedback": lambda: _import_runs(
            db, "feedback", feedback.FeedbackRun, settings.feedback_dir, "runs"
        ),
        "comments": lambda: _import_comments(db, settings.feedback_dir),
        "test_configs": lambda: _import_configs(db, settings.test_configs_dir),
    }
    imported: dict[str, int] = {}
    for name, job in jobs.items():
        flag = f"legacy_import:{name}"
        if db.meta(flag):
            continue
        imported[name] = job()
        db.set_meta(flag, "done")
    return imported
