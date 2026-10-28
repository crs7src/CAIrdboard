from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app import skills
from app.db import RunStore
from app.implementer import (
    ACTIVE_REPOS,
    DENIED_TOOLS,
    Commit,
    Implementation,
    ImplementationError,
    _git,
    list_commits,
)
from app.jira import Card
from app.planner import (
    CommandNotFound,
    CommandTimeout,
    format_comments,
    format_history,
    needs_rework,
    run_command,
)
from app.skills import SkillError

# running: in progress; clean: reviewed with nothing to fix; fixed: the reviewer
# committed fixes, so the result needs another review; failed: the run broke.
ReviewState = Literal["running", "clean", "fixed", "failed"]


class Review(BaseModel):
    card_key: str
    version: int
    implementation_version: int
    state: ReviewState
    branch: str | None = None
    base_commit: str | None = None
    head_before: str | None = None
    fix_commits: list[Commit] = []
    notes: list[str] = []
    report: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReviewStore(RunStore[Review]):
    kind = "review"
    model = Review
    clears_approval_on_create = True
    clears_approval_on_states = frozenset({"fixed"})

    def create(self, key: str, impl: Implementation) -> Review:
        def build(version: int, stamp: str):
            run = Review(
                card_key=key,
                version=version,
                implementation_version=impl.version,
                state="running",
                branch=impl.branch,
                base_commit=impl.base_commit,
                created_at=stamp,
                updated_at=stamp,
            )
            return run

        return self.create_run(key, build)


# Card keys with a review in this server process (repos are tracked in the
# implementer's ACTIVE_REPOS so a review and an implementation never share a repo).
ACTIVE: set[str] = set()


def recover_stale(store: ReviewStore, run: Review | None) -> Review | None:
    if run and run.state == "running" and run.card_key not in ACTIVE:
        run.state = "failed"
        run.error = "Interrupted before it finished. Check the branch and review again."
        store.save(run)
    return run


def load_skill(path: Path | None = None) -> str:
    """The reviewer skill: the given file, else the user's override or the default."""
    if path is None:
        return skills.strip_frontmatter(skills.read("reviewer"))
    try:
        text = path.read_text()
    except OSError as e:
        raise SkillError(f"Reviewer skill file could not be read: {path}") from e
    return skills.strip_frontmatter(text)


def build_prompt(
    card: Card,
    plan_text: str,
    impl: Implementation,
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
        f"Base commit (review the diff {impl.base_commit or '(unknown)'}..HEAD)",
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
    if impl.report:
        parts += ["", "Implementer's report:", impl.report]
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


async def run_review(
    store: ReviewStore,
    run: Review,
    impl: Implementation,
    card: Card,
    plan_text: str,
    repo: str,
    command: str,
    timeout: float,
    runner=run_command,
) -> None:
    """Review the card's branch in a fresh AI session and record the outcome. Never raises."""
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

        prompt = build_prompt(card, plan_text, impl, skill)
        result = await runner(build_args(command, prompt), repo, timeout)
        run.fix_commits = await list_commits(runner, repo, run.head_before)

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
        run.report = output or None
        run.state = "fixed" if run.fix_commits else "clean"
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
