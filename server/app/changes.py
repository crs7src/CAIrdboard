import re

from pydantic import BaseModel

from app.implementer import Implementation, _git

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


class ChangeCommit(BaseModel):
    sha: str
    short: str
    subject: str


class Changes(BaseModel):
    branch: str
    base_commit: str
    commits: list[ChangeCommit]
    selected_commit: str | None = None
    diff: str


async def load_changes(
    runner, repo: str, impl: Implementation, commit: str | None = None
) -> Changes:
    """Unified diff of everything on the card's branch since its base commit.

    Read-only: only `git log` and `git diff`/`git show` are run. With `commit`, the
    diff is limited to that one commit (which must belong to the branch's range).
    """
    assert impl.branch and impl.base_commit
    span = f"{impl.base_commit}..{impl.branch}"
    log = await _git(runner, repo, "log", "--reverse", "--format=%H%x1f%s", span)
    commits = []
    for line in log.splitlines():
        sha, _, subject = line.partition("\x1f")
        commits.append(ChangeCommit(sha=sha, short=sha[:7], subject=subject))

    selected = None
    if commit:
        selected = next((c for c in commits if c.sha.startswith(commit)), None)
        if not SHA_RE.match(commit) or selected is None:
            raise ValueError(f"Commit {commit} is not part of {impl.branch}")
        args = ["show", "--format=", "--no-color", "--no-ext-diff", "-M", selected.sha]
    else:
        args = ["diff", "--no-color", "--no-ext-diff", "-M", span]
    diff = await _git(runner, repo, *args)
    return Changes(
        branch=impl.branch,
        base_commit=impl.base_commit,
        commits=commits,
        selected_commit=selected.sha if selected else None,
        diff=diff + "\n" if diff else "",
    )
