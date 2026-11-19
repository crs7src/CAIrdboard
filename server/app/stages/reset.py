from pydantic import BaseModel

from app.core.db import Database, Resets, delete_card_data
from app.stages import (
    feedback,
    implementer,
    merge_request,
    planner,
    reviewer,
    tester,
)


class ResetError(Exception):
    """The reset cannot happen (busy card or repo, dirty repo, git failure)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class ResetResult(BaseModel):
    branch: str | None = None
    branch_deleted: bool = False
    deleted_sha: str | None = None
    notes: list[str] = []


def is_busy(key: str) -> bool:
    """A plan, implementation, review, feedback or merge request run is active."""
    return any(
        key in active
        for active in (
            planner.ACTIVE,
            implementer.ACTIVE,
            reviewer.ACTIVE,
            reviewer.PENDING,
            feedback.ACTIVE,
            merge_request.ACTIVE,
        )
    )


async def _card_branch(runner, repo: str, db: Database, key: str) -> str | None:
    run = implementer.ImplementationStore(db).latest(key)
    if run and run.branch:
        return run.branch
    return await implementer._existing_branch(runner, repo, key)


async def _delete_branch(runner, repo: str, branch: str, result: ResetResult) -> None:
    git = implementer._git
    if not await implementer._git_ok(
        runner, repo, "rev-parse", "--verify", f"refs/heads/{branch}"
    ):
        result.notes.append(f"Branch {branch} no longer exists locally.")
        return
    if await git(runner, repo, "status", "--porcelain"):
        raise ResetError(
            "The repo has uncommitted changes. Commit or stash them first."
        )
    if await git(runner, repo, "rev-parse", "--abbrev-ref", "HEAD") == branch:
        await git(
            runner, repo, "checkout", await implementer._default_branch(runner, repo)
        )
    result.deleted_sha = await git(runner, repo, "rev-parse", branch)
    await git(runner, repo, "branch", "-D", branch)
    result.branch_deleted = True
    result.notes.append(
        f"Deleted local branch {branch} (was at {result.deleted_sha[:10]}). "
        "The remote branch and any merge request were left alone."
    )


async def reset_card(
    runner,
    db: Database,
    test_store: tester.TestStore,
    key: str,
    repo: str,
    delete_branch: bool = True,
) -> ResetResult:
    """Clear all progress of a card, optionally deleting its local branch."""
    if is_busy(key):
        raise ResetError("A run is active for this card. Wait for it to finish.")
    # Stopping the card's own test app also frees the repo it holds.
    await tester.stop_app(test_store, key)
    if repo in implementer.ACTIVE_REPOS:
        raise ResetError("The repo is busy with another run. Try again shortly.")

    implementer.ACTIVE_REPOS.add(repo)
    try:
        result = ResetResult()
        if delete_branch:
            try:
                result.branch = await _card_branch(runner, repo, db, key)
                if result.branch:
                    await _delete_branch(runner, repo, result.branch, result)
                else:
                    result.notes.append("The card has no branch.")
            except implementer.ImplementationError as e:
                raise ResetError(str(e), 502) from e
        delete_card_data(db, key)
        Resets(db).mark(key, "reset")
        return result
    finally:
        implementer.ACTIVE_REPOS.discard(repo)
