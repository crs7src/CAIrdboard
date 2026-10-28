import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.core import skills
from app.core.db import RunStore, check_key
from app.core.skills import SkillError
from app.integrations.jira import Card
from app.stages.implementer import (
    ACTIVE_REPOS,
    DENIED_TOOLS,
    Commit,
    Implementation,
    ImplementationError,
    _git,
    list_commits,
)
from app.stages.planner import (
    CommandNotFound,
    CommandTimeout,
    format_comments,
    format_history,
    needs_rework,
    run_command,
)

CommentStatus = Literal["pending", "resolved"]
FeedbackState = Literal["running", "done", "failed"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CommentInput(BaseModel):
    """A general comment (no file) or a comment on one line of one file."""

    text: str
    file: str | None = None
    line: int | None = None
    # "new": the line in the branch's version; "old": a deleted line of the base version.
    side: Literal["new", "old"] = "new"
    code: str | None = None
    # Where the comment came from: the code review, or issues found by manual testing.
    origin: Literal["review", "testing"] = "review"

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A comment cannot be empty")
        return v

    @field_validator("file")
    @classmethod
    def file_not_blank(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None

    @model_validator(mode="after")
    def line_needs_file(self):
        if self.line is not None and (not self.file or self.line < 1):
            raise ValueError(
                "A line comment needs a file and a line number of 1 or more"
            )
        return self


class FeedbackComment(CommentInput):
    id: str
    status: CommentStatus = "pending"
    resolved_in: int | None = None
    created_at: str


class FeedbackRun(BaseModel):
    card_key: str
    version: int
    state: FeedbackState
    branch: str | None = None
    head_before: str | None = None
    comments: list[FeedbackComment] = []
    commits: list[Commit] = []
    notes: list[str] = []
    report: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class FeedbackStore(RunStore[FeedbackRun]):
    """Runs are versioned rows; the comments for a card live in their own table."""

    kind = "feedback"
    model = FeedbackRun
    clears_approval_on_create = True
    clears_approval_on_states = frozenset({"done"})

    def comments(self, key: str) -> list[FeedbackComment]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT data FROM comments WHERE card_key = ? ORDER BY rowid",
                (check_key(key),),
            ).fetchall()
        return [FeedbackComment.model_validate_json(r[0]) for r in rows]

    def save_comments(self, key: str, comments: list[FeedbackComment]) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM comments WHERE card_key = ?", (check_key(key),))
            conn.executemany(
                "INSERT INTO comments (card_key, id, data) VALUES (?, ?, ?)",
                [(key, c.id, c.model_dump_json()) for c in comments],
            )

    def add(self, key: str, data: CommentInput) -> FeedbackComment:
        comment = FeedbackComment(
            **data.model_dump(), id=uuid.uuid4().hex[:8], created_at=_now()
        )
        self.save_comments(key, [*self.comments(key), comment])
        return comment

    def edit(self, key: str, comment_id: str, text: str) -> FeedbackComment | None:
        comments = self.comments(key)
        for c in comments:
            if c.id == comment_id and c.status == "pending":
                c.text = text
                self.save_comments(key, comments)
                return c
        return None

    def delete(self, key: str, comment_id: str) -> bool:
        comments = self.comments(key)
        kept = [
            c for c in comments if not (c.id == comment_id and c.status == "pending")
        ]
        if len(kept) == len(comments):
            return False
        self.save_comments(key, kept)
        return True

    def resolve(self, key: str, ids: set[str], version: int) -> None:
        comments = self.comments(key)
        for c in comments:
            if c.id in ids:
                c.status, c.resolved_in = "resolved", version
        self.save_comments(key, comments)

    def create(self, key: str, impl: Implementation) -> FeedbackRun:
        def build(version: int, stamp: str):
            run = FeedbackRun(
                card_key=key,
                version=version,
                state="running",
                branch=impl.branch,
                comments=[c for c in self.comments(key) if c.status == "pending"],
                created_at=stamp,
                updated_at=stamp,
            )
            return run

        return self.create_run(key, build)


# Card keys with a feedback run in this server process (repos are tracked in the
# implementer's ACTIVE_REPOS so it never shares a repo with another run).
ACTIVE: set[str] = set()


def recover_stale(store: FeedbackStore, run: FeedbackRun | None) -> FeedbackRun | None:
    if run and run.state == "running" and run.card_key not in ACTIVE:
        run.state = "failed"
        run.error = "Interrupted before it finished. Check the branch and submit again."
        store.save(run)
    return run


def load_skill() -> str:
    return skills.strip_frontmatter(skills.read("feedback"))


def format_comment(index: int, c: FeedbackComment) -> str:
    if c.origin == "testing":
        return f"{index}. [manual testing] {c.text}"
    if not c.file:
        return f"{index}. [general] {c.text}"
    where = c.file
    if c.line:
        side = "deleted line in the old version" if c.side == "old" else "line"
        where += f", {side} {c.line}"
    code = f"\n   Code: `{c.code.strip()}`" if c.code else ""
    return f"{index}. [{where}] {c.text}{code}"


def build_prompt(
    card: Card,
    plan_text: str,
    impl: Implementation,
    comments: list[FeedbackComment],
    skill: str | None = None,
) -> str:
    parts = [
        skills.AGENTS_PREAMBLE,
        "",
        skill if skill is not None else load_skill(),
        "",
        f"Card: {card.key} - {card.summary}",
        f"{card.source_label} status: {card.status}",
        f"Current branch (already checked out): {impl.branch}",
        f"Base commit (the changes under review are {impl.base_commit or '(unknown)'}..HEAD)",
        "",
        "Description:",
        card.description or "(no description)",
        "",
        "Comments (oldest first):",
        format_comments(card),
    ]
    if needs_rework(card) and card.status_history:
        parts += [
            "",
            "This card has been Reopened. Status history (oldest first):",
            format_history(card),
        ]
    parts += ["", "Approved plan:", plan_text]
    parts += [
        "",
        (
            "Feedback to address (code review and/or manual testing; line numbers "
            "refer to the files as they are now, at HEAD, unless marked as an "
            "old-version line):"
        ),
        *(format_comment(i, c) for i, c in enumerate(comments, 1)),
    ]
    return "\n".join(parts)


def build_args(command: str, prompt: str) -> list[str]:
    return [
        command,
        "-s",
        "-p",
        prompt,
        "--allow-all-tools",
        "--no-ask-user",
        "--deny-tool",
        *DENIED_TOOLS,
    ]


async def run_feedback(
    store: FeedbackStore,
    run: FeedbackRun,
    impl: Implementation,
    card: Card,
    plan_text: str,
    repo: str,
    command: str,
    timeout: float,
    runner=run_command,
) -> None:
    """Make the requested edits in a fresh AI session and record the outcome. Never raises."""
    try:
        skill = load_skill()
        branch = impl.branch or ""
        if await _git(runner, repo, "status", "--porcelain"):
            raise ImplementationError(
                "The repo has uncommitted changes. Commit or stash them first."
            )
        await _git(runner, repo, "checkout", branch)
        run.head_before = await _git(runner, repo, "rev-parse", "HEAD")
        store.save(run)

        prompt = build_prompt(card, plan_text, impl, run.comments, skill)
        result = await runner(build_args(command, prompt), repo, timeout)
        run.commits = await list_commits(runner, repo, run.head_before)

        current = await _git(runner, repo, "rev-parse", "--abbrev-ref", "HEAD")
        if await _git(runner, repo, "status", "--porcelain"):
            run.notes.append("Some changes were left uncommitted in the working tree.")
        output = result.stdout.strip()
        if result.returncode != 0:
            raise ImplementationError(
                (result.stderr.strip() or output or "The AI exited with an error")[
                    :2000
                ]
            )
        if current != branch:
            raise ImplementationError(
                f"The AI left the branch (now on '{current}', expected '{branch}')"
            )
        if not run.commits:
            run.notes.append("The AI made no commits.")
        run.report = output or None
        run.state = "done"
        store.resolve(run.card_key, {c.id for c in run.comments}, run.version)
    except (SkillError, ImplementationError) as e:
        run.state, run.error = "failed", str(e)
    except CommandTimeout:
        run.state, run.error = "failed", f"Timed out after {int(timeout)}s"
    except CommandNotFound:
        run.state, run.error = "failed", f"Command not found: {command}"
    except Exception as e:  # noqa: BLE001 - record any failure on the run
        run.state, run.error = "failed", f"Unexpected error: {e}"
    finally:
        ACTIVE.discard(run.card_key)
        ACTIVE_REPOS.discard(repo)
        store.save(run)
