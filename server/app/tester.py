import asyncio
import json
import os
import re
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from app import skills
from app.implementer import (
    ACTIVE_REPOS,
    DENIED_TOOLS,
    Implementation,
    ImplementationError,
    _git,
)
from app.jira import Card
from app.planner import (
    CARD_KEY_RE,
    CommandNotFound,
    CommandTimeout,
    format_comments,
    format_history,
    needs_rework,
    run_command,
)
from app.skills import SkillError

# preparing: the AI is working out how to run the app, or the app is starting;
# running: the app is up; stopped: it was stopped or exited; failed: it never came up.
TestState = Literal["preparing", "running", "stopped", "failed"]
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL)
LOG_TAIL_LINES = 30


class TesterError(Exception):
    pass


def check_local_url(url: str) -> str:
    """Only http(s) URLs on this machine: these become clickable links."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError(f"'{url}' is not a local http(s) URL (use localhost)")
    return url


class TestLink(BaseModel):
    __test__ = False  # not a pytest class

    title: str
    url: str
    check: str = ""

    @field_validator("url")
    @classmethod
    def local_only(cls, v: str) -> str:
        return check_local_url(v)


LEGACY_APP_FIELDS = ("start_command", "workdir", "ready_url")


def upgrade_single_app(data):
    """Accept the old single-app shape (start_command/workdir/ready_url) as a one-app list."""
    if isinstance(data, dict) and "apps" not in data and "start_command" in data:
        data = dict(data)
        data["apps"] = [
            {"name": "app", **{k: data.pop(k) for k in LEGACY_APP_FIELDS if k in data}}
        ]
    return data


class AppSpec(BaseModel):
    """One process to start for manual testing."""

    name: str = "app"
    start_command: str
    workdir: str = "."
    ready_url: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("an app has no name")
        return v.strip()

    @field_validator("start_command")
    @classmethod
    def command_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("start_command is empty")
        return v.strip()

    @field_validator("ready_url")
    @classmethod
    def ready_local(cls, v: str) -> str:
        return check_local_url(v)


def _unique_names(apps: list[AppSpec]) -> list[AppSpec]:
    names = [a.name for a in apps]
    if len(set(names)) != len(names):
        raise ValueError("app names must be unique")
    return apps


class TesterOutput(BaseModel):
    """What the AI must report in a final ```json block."""

    apps: Annotated[list[AppSpec], Field(min_length=1)]
    links: list[TestLink]
    summary: str = ""

    _check_names = field_validator("apps")(_unique_names)

    @model_validator(mode="before")
    @classmethod
    def legacy(cls, data):
        return upgrade_single_app(data)


class TestRun(BaseModel):
    __test__ = False

    card_key: str
    version: int
    review_version: int | None = None
    state: TestState
    branch: str | None = None
    apps: list[AppSpec] = []
    links: list[TestLink] = []
    notes: list[str] = []
    report: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str

    @model_validator(mode="before")
    @classmethod
    def legacy(cls, data):
        if isinstance(data, dict) and data.get("start_command") and "apps" not in data:
            return upgrade_single_app(data)
        return data


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TestStore:
    """One JSON file per run: <root>/<CARD-KEY>/<version>.json (plus <version>-app<n>.log per app)."""

    __test__ = False

    def __init__(self, root: Path):
        self.root = root

    def _dir(self, key: str) -> Path:
        if not CARD_KEY_RE.match(key):
            raise ValueError(f"Invalid card key: {key}")
        return self.root / key

    def log_path(self, run: TestRun, index: int) -> Path:
        return self._dir(run.card_key) / f"{run.version}-app{index + 1}.log"

    def versions(self, key: str) -> list[TestRun]:
        d = self._dir(key)
        if not d.exists():
            return []
        runs = [TestRun.model_validate_json(p.read_text()) for p in d.glob("*.json")]
        return sorted(runs, key=lambda r: r.version)

    def latest(self, key: str) -> TestRun | None:
        runs = self.versions(key)
        return runs[-1] if runs else None

    def create(self, key: str, impl: Implementation, review_version: int) -> TestRun:
        latest = self.latest(key)
        now = _now()
        run = TestRun(
            card_key=key,
            version=(latest.version + 1) if latest else 1,
            review_version=review_version,
            state="preparing",
            branch=impl.branch,
            created_at=now,
            updated_at=now,
        )
        return self.save(run)

    def save(self, run: TestRun) -> TestRun:
        run.updated_at = _now()
        d = self._dir(run.card_key)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{run.version}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(run.model_dump_json(indent=2))
        os.replace(tmp, path)
        return run


@dataclass
class Running:
    """The processes started for one card, in start order."""

    repo: str
    processes: list[tuple[str, asyncio.subprocess.Process]]
    monitors: list[asyncio.Task]


# Card keys that are preparing or running in this server process, and the apps we started.
ACTIVE: set[str] = set()
APPS: dict[str, Running] = {}


def recover_stale(store: TestStore, run: TestRun | None) -> TestRun | None:
    if run and run.state in ("preparing", "running") and run.card_key not in ACTIVE:
        if run.state == "running":
            run.state = "stopped"
            run.notes.append("The server restarted, so the app is no longer running.")
        else:
            run.state = "failed"
            run.error = "Interrupted before it finished. Start the test again."
        store.save(run)
    return run


def load_skill() -> str:
    return skills.strip_frontmatter(skills.read("tester"))


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
        f"Jira status: {card.status}",
        f"Current branch (already checked out): {impl.branch}",
        f"Base commit (the changes are {impl.base_commit or '(unknown)'}..HEAD)",
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


def parse_output(text: str) -> TesterOutput:
    """Read the last ```json block of the AI's final message."""
    blocks = JSON_BLOCK_RE.findall(text)
    if not blocks:
        raise TesterError("The AI did not report how to run the app (no JSON block)")
    try:
        return TesterOutput.model_validate(json.loads(blocks[-1]))
    except (json.JSONDecodeError, ValueError) as e:
        raise TesterError(f"The AI's run instructions were invalid: {e}") from e


def resolve_workdir(repo: str, workdir: str) -> Path:
    root = Path(repo).resolve()
    path = (root / workdir).resolve()
    if path != root and root not in path.parents:
        raise TesterError(f"The app folder '{workdir}' is outside the repo")
    if not path.is_dir():
        raise TesterError(f"The app folder '{workdir}' does not exist")
    return path


async def start_app(command: str, cwd: Path, log_path: Path):
    """Start the app in its own process group so the whole tree can be stopped."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        return await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )


async def probe_url(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2, verify=False) as client:
            await client.get(url)
        return True
    except httpx.HTTPError:
        return False


def log_tail(path: Path) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), wait)
            return
        except TimeoutError:
            continue


def release(key: str, repo: str) -> None:
    ACTIVE.discard(key)
    APPS.pop(key, None)
    ACTIVE_REPOS.discard(repo)


async def stop_processes(running: Running) -> None:
    """Stop the apps in reverse start order (dependents first)."""
    for task in running.monitors:
        task.cancel()
    for _, process in reversed(running.processes):
        await stop_process(process)


async def stop_app(store: TestStore, key: str) -> TestRun | None:
    """Stop all of the card's running apps (if any) and free the repo."""
    running = APPS.get(key)
    run = store.latest(key)
    if running:
        await stop_processes(running)
        release(key, running.repo)
    if run and run.state in ("preparing", "running") and running:
        run.state = "stopped"
        store.save(run)
    return run


async def stop_all(store_root: Path) -> None:
    for key in list(APPS):
        await stop_app(TestStore(store_root), key)


async def wait_ready(process, url: str, timeout: float, probe=probe_url) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if process.returncode is not None:
            return False
        if await probe(url):
            return True
        await asyncio.sleep(0.5)
    return False


async def _watch(
    store: TestStore, run: TestRun, running: Running, name: str, process
) -> None:
    """If one app exits by itself, stop the others, record it and free the repo."""
    code = await process.wait()
    run.state = "stopped"
    run.notes.append(
        f"The '{name}' app exited (code {code}), so all apps were stopped."
    )
    store.save(run)
    me = asyncio.current_task()
    for task in running.monitors:
        if task is not me:
            task.cancel()
    for _, other in reversed(running.processes):
        await stop_process(other)
    release(run.card_key, running.repo)


async def run_test(
    store: TestStore,
    run: TestRun,
    impl: Implementation,
    card: Card,
    plan_text: str,
    repo: str,
    command: str,
    timeout: float,
    ready_timeout: float,
    runner=run_command,
    spawner=start_app,
    probe=probe_url,
) -> None:
    """Work out how to run the card's branch, start it and wait until it responds.

    Never raises. On success the app keeps running (and the repo stays locked)
    until it is stopped.
    """
    try:
        skill = load_skill()
        branch = impl.branch or ""
        if await _git(runner, repo, "status", "--porcelain"):
            raise ImplementationError(
                "The repo has uncommitted changes. Commit or stash them first."
            )
        await _git(runner, repo, "checkout", branch)

        prompt = build_prompt(card, plan_text, impl, skill)
        result = await runner(build_args(command, prompt), repo, timeout)
        output = result.stdout.strip()
        if result.returncode != 0:
            raise ImplementationError(
                (result.stderr.strip() or output or "The AI exited with an error")[
                    :2000
                ]
            )
        current = await _git(runner, repo, "rev-parse", "--abbrev-ref", "HEAD")
        if current != branch:
            raise ImplementationError(
                f"The AI left the branch (now on '{current}', expected '{branch}')"
            )
        if await _git(runner, repo, "status", "--porcelain"):
            run.notes.append("Some changes were left uncommitted in the working tree.")

        plan = parse_output(output)
        workdirs = [resolve_workdir(repo, a.workdir) for a in plan.apps]
        run.apps, run.links = plan.apps, plan.links
        run.report = plan.summary or None
        store.save(run)

        running = Running(repo, [], [])
        APPS[run.card_key] = running
        for i, (spec, workdir) in enumerate(zip(plan.apps, workdirs, strict=True)):
            log = store.log_path(run, i)
            process = await spawner(spec.start_command, workdir, log)
            running.processes.append((spec.name, process))
            if not await wait_ready(process, spec.ready_url, ready_timeout, probe):
                why = (
                    f"The '{spec.name}' app exited (code {process.returncode})"
                    if process.returncode is not None
                    else f"The '{spec.name}' app did not respond at {spec.ready_url} "
                    f"within {int(ready_timeout)}s"
                )
                raise TesterError(f"{why}.\n{log_tail(log)}".strip())
        run.state = "running"
        store.save(run)
        running.monitors = [
            asyncio.create_task(_watch(store, run, running, name, process))
            for name, process in running.processes
        ]
    except (SkillError, ImplementationError, TesterError) as e:
        run.state, run.error = "failed", str(e)
    except CommandTimeout:
        run.state, run.error = "failed", f"Timed out after {int(timeout)}s"
    except CommandNotFound:
        run.state, run.error = "failed", f"Command not found: {command}"
    except Exception as e:  # noqa: BLE001 - record any failure on the run
        run.state, run.error = "failed", f"Unexpected error: {e}"
    finally:
        if run.state == "failed":
            running = APPS.get(run.card_key)
            if running:
                await stop_processes(running)
            release(run.card_key, repo)
        store.save(run)
