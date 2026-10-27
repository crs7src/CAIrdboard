import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.jira import Card
from app.planner import (
    CARD_KEY_RE,
    READ_ONLY_TOOLS,
    CommandNotFound,
    CommandTimeout,
    format_comments,
    format_history,
    needs_rework,
    run_command,
)

ImplState = Literal["running", "completed", "failed"]
ImplStage = Literal["preparing", "implementing", "done"]

SKILL_PATH = (
    Path(__file__).resolve().parent.parent / "skills" / "card-implementer" / "SKILL.md"
)

# The implementer may edit files and run commands, but never publish anything,
# rewrite history, or destroy work. It may checkout/switch, but run_implementation
# fails the run if it does not end on its own branch.
DENIED_TOOLS = [
    "shell(git push)",
    "shell(git branch)",
    "shell(git rebase)",
    "shell(git reset --hard)",
    "shell(git clean)",
    "shell(rm -rf)",
    "shell(sudo)",
]

DEFAULT_BRANCHES = ("main", "master")
GIT_TIMEOUT = 120
PULL_TIMEOUT = 300
SUMMARY_TIMEOUT = 180


class Commit(BaseModel):
    sha: str
    subject: str


class Implementation(BaseModel):
    card_key: str
    version: int
    plan_version: int
    state: ImplState
    stage: ImplStage = "preparing"
    branch: str | None = None
    base_branch: str | None = None
    base_commit: str | None = None
    commits: list[Commit] = []
    notes: list[str] = []
    report: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ImplementationError(Exception):
    """A step before or after the AI run failed in a way the user should see."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ImplementationStore:
    """One JSON file per run: <root>/<CARD-KEY>/<version>.json."""

    def __init__(self, root: Path):
        self.root = root

    def _dir(self, key: str) -> Path:
        if not CARD_KEY_RE.match(key):
            raise ValueError(f"Invalid card key: {key}")
        return self.root / key

    def versions(self, key: str) -> list[Implementation]:
        d = self._dir(key)
        if not d.exists():
            return []
        runs = [
            Implementation.model_validate_json(p.read_text()) for p in d.glob("*.json")
        ]
        return sorted(runs, key=lambda r: r.version)

    def latest(self, key: str) -> Implementation | None:
        runs = self.versions(key)
        return runs[-1] if runs else None

    def create(self, key: str, plan_version: int) -> Implementation:
        latest = self.latest(key)
        now = _now()
        run = Implementation(
            card_key=key,
            version=(latest.version + 1) if latest else 1,
            plan_version=plan_version,
            state="running",
            created_at=now,
            updated_at=now,
        )
        self.save(run)
        return run

    def save(self, run: Implementation) -> Implementation:
        run.updated_at = _now()
        d = self._dir(run.card_key)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{run.version}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(run.model_dump_json(indent=2))
        os.replace(tmp, path)
        return run


# Card keys and repo paths with a run in this server process. The caller adds them
# before scheduling run_implementation(), which removes them when finished.
ACTIVE: set[str] = set()
ACTIVE_REPOS: set[str] = set()


def recover_stale(
    store: ImplementationStore, run: Implementation | None
) -> Implementation | None:
    """A 'running' run with no live task was interrupted (e.g. server restart)."""
    if run and run.state == "running" and run.card_key not in ACTIVE:
        run.state = "failed"
        run.error = "Interrupted before it finished. Check the branch and start again."
        store.save(run)
    return run


# ---- git helpers -----------------------------------------------------------


async def _git(runner, repo: str, *args: str, timeout: float = GIT_TIMEOUT) -> str:
    try:
        result = await runner(["git", *args], repo, timeout)
    except CommandNotFound as e:
        raise ImplementationError("git is not installed") from e
    except CommandTimeout as e:
        raise ImplementationError(f"git {args[0]} timed out") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ImplementationError(f"git {' '.join(args)} failed: {detail}"[:1000])
    return result.stdout.strip()


async def _git_ok(runner, repo: str, *args: str) -> bool:
    try:
        await _git(runner, repo, *args)
    except ImplementationError:
        return False
    return True


def slugify(text: str, max_words: int = 6, max_len: int = 40) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "_".join(words)[:max_len].strip("_")


def branch_name(key: str, summary_slug: str) -> str:
    return f"{key}_{summary_slug}" if summary_slug else key


async def _default_branch(runner, repo: str) -> str:
    for name in DEFAULT_BRANCHES:
        if await _git_ok(runner, repo, "rev-parse", "--verify", f"refs/heads/{name}"):
            return name
    raise ImplementationError("Could not find a local main or master branch")


async def _existing_branch(runner, repo: str, key: str) -> str | None:
    out = await _git(
        runner,
        repo,
        "branch",
        "--list",
        f"{key}_*",
        "--sort=-committerdate",
        "--format=%(refname:short)",
    )
    names = [n for n in out.splitlines() if n]
    return names[0] if names else None


async def summarize_change(
    runner, command: str, repo: str, card: Card, plan_text: str
) -> str:
    """Ask the AI for a few words describing the change; fall back to the card title."""
    prompt = (
        "Reply with ONLY a 2 to 5 word lowercase summary of the code change described "
        "by this plan, suitable for a git branch name. No punctuation, no quotes, no "
        f"explanation.\n\nCard: {card.key} - {card.summary}\n\nPlan:\n{plan_text}"
    )
    args = [command, "-s", "-p", prompt, "--available-tools", *READ_ONLY_TOOLS]
    try:
        result = await runner(args, repo, SUMMARY_TIMEOUT)
        if result.returncode == 0:
            first_line = (result.stdout.strip().splitlines() or [""])[0]
            slug = slugify(first_line)
            if slug:
                return slug
    except CommandTimeout, CommandNotFound:
        pass
    return slugify(card.summary)


async def prepare_branch(
    runner, command: str, repo: str, card: Card, plan_text: str, run: Implementation
) -> None:
    """Check out a clean branch for the card, recording what happened on `run`."""
    if not await _git_ok(runner, repo, "rev-parse", "--is-inside-work-tree"):
        raise ImplementationError(f"{repo} is not a git repository")
    if await _git(runner, repo, "status", "--porcelain"):
        raise ImplementationError(
            "The repo has uncommitted changes. Commit or stash them first."
        )

    existing = await _existing_branch(runner, repo, card.key)
    if existing:
        await _git(runner, repo, "checkout", existing)
        run.branch = existing
        run.notes.append(f"Continuing on existing branch {existing}.")
        run.base_commit = await _git(runner, repo, "rev-parse", "HEAD")
        return

    base = await _default_branch(runner, repo)
    await _git(runner, repo, "checkout", base)
    remotes = (await _git(runner, repo, "remote")).split()
    if "origin" in remotes:
        await _git(
            runner, repo, "pull", "--ff-only", "origin", base, timeout=PULL_TIMEOUT
        )
    else:
        run.notes.append(
            f"No 'origin' remote; branched from local {base} without pulling."
        )
    run.base_branch = base

    slug = await summarize_change(runner, command, repo, card, plan_text)
    name = branch_name(card.key, slug)
    if not await _git_ok(runner, repo, "check-ref-format", "--branch", name):
        name = card.key
    await _git(runner, repo, "checkout", "-b", name)
    run.branch = name
    run.base_commit = await _git(runner, repo, "rev-parse", "HEAD")


async def list_commits(runner, repo: str, base_commit: str | None) -> list[Commit]:
    if not base_commit:
        return []
    out = await _git(
        runner, repo, "log", "--reverse", "--format=%H%x1f%s", f"{base_commit}..HEAD"
    )
    commits = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x1f")
        commits.append(Commit(sha=sha[:10], subject=subject))
    return commits


# ---- prompt and AI run ------------------------------------------------------


class SkillError(Exception):
    pass


def load_skill(path: Path = SKILL_PATH) -> str:
    try:
        text = path.read_text()
    except OSError as e:
        raise SkillError(f"Implementer skill file could not be read: {path}") from e
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return text.strip()


def build_prompt(
    card: Card,
    plan_text: str,
    branch: str,
    base_commit: str | None,
    skill: str | None = None,
) -> str:
    parts = [
        skill if skill is not None else load_skill(),
        "",
        f"Card: {card.key} - {card.summary}",
        f"Jira status: {card.status}",
        f"Priority: {card.priority or 'none'}",
        f"Current branch (already checked out): {branch}",
        f"Base commit for your final review diff: {base_commit or '(unknown)'}",
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
    parts += ["", "Approved plan to implement:", plan_text]
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


async def run_implementation(
    store: ImplementationStore,
    run: Implementation,
    card: Card,
    plan_text: str,
    repo: str,
    command: str,
    timeout: float,
    runner=run_command,
) -> None:
    """Prepare the branch, run the AI, and record the outcome. Never raises."""
    try:
        skill = load_skill()
        await prepare_branch(runner, command, repo, card, plan_text, run)
        run.stage = "implementing"
        store.save(run)

        prompt = build_prompt(card, plan_text, run.branch or "", run.base_commit, skill)
        result = await runner(build_args(command, prompt), repo, timeout)
        run.commits = await list_commits(runner, repo, run.base_commit)

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
        if current != run.branch:
            raise ImplementationError(
                f"The AI left the branch (now on '{current}', expected '{run.branch}')"
            )
        if not run.commits:
            raise ImplementationError("The AI finished without making any commits")
        run.state, run.report = "completed", output or None
    except SkillError as e:
        run.state, run.error = "failed", str(e)
    except ImplementationError as e:
        run.state, run.error = "failed", str(e)
    except CommandTimeout:
        run.state, run.error = "failed", f"Timed out after {int(timeout)}s"
    except CommandNotFound:
        run.state, run.error = "failed", f"Command not found: {command}"
    except Exception as e:  # noqa: BLE001 - record any failure on the run
        run.state, run.error = "failed", f"Unexpected error: {e}"
    finally:
        run.stage = "done"
        ACTIVE.discard(run.card_key)
        ACTIVE_REPOS.discard(repo)
        store.save(run)
