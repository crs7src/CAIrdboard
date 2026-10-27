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
from app.db import Database, RunStore, check_key
from app.implementer import (
    ACTIVE_REPOS,
    DENIED_TOOLS,
    Implementation,
    ImplementationError,
    _git,
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

# preparing: the AI is working out how to run the app, or the app is starting;
# running: the app is up; stopped: it was stopped or exited; failed: it never came up.
TestState = Literal["preparing", "running", "stopped", "failed"]
# ai: the AI worked out how to run it; saved: reused the project's saved settings;
# feedback: the AI fixed the settings after the user reported a problem.
TestSource = Literal["ai", "saved", "feedback"]
PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL)
LOG_TAIL_LINES = 30
MAX_READY_TIMEOUT = 600


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
    ready_timeout_seconds: Annotated[int, Field(ge=1, le=MAX_READY_TIMEOUT)] | None = (
        None
    )

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
    source: TestSource = "ai"
    problem: str | None = None
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


class TestStore(RunStore[TestRun]):
    """Runs are versioned rows; each app's log is <logs>/<KEY>/<version>-app<n>.log."""

    __test__ = False
    kind = "test"
    model = TestRun

    def __init__(self, db: Database, logs_root: Path):
        super().__init__(db)
        self.logs_root = logs_root

    def log_path(self, run: TestRun, index: int) -> Path:
        return (
            self.logs_root
            / check_key(run.card_key)
            / f"{run.version}-app{index + 1}.log"
        )

    def create(
        self,
        key: str,
        impl: Implementation,
        review_version: int,
        source: TestSource = "ai",
        problem: str | None = None,
    ) -> TestRun:
        def build(version: int, stamp: str):
            run = TestRun(
                card_key=key,
                version=version,
                review_version=review_version,
                state="preparing",
                source=source,
                problem=problem,
                branch=impl.branch,
                created_at=stamp,
                updated_at=stamp,
            )
            return run

        return self.create_run(key, build)


class SavedConfig(BaseModel):
    """How the project's apps were last started successfully."""

    project: str
    apps: list[AppSpec]
    saved_from: str
    saved_at: str


class ConfigStore:
    """One saved set of apps per Jira project."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _check(project: str) -> str:
        if not PROJECT_RE.match(project):
            raise ValueError(f"Invalid project key: {project}")
        return project

    def load(self, project: str) -> SavedConfig | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT data FROM test_configs WHERE project = ?",
                (self._check(project),),
            ).fetchone()
        if row is None:
            return None
        try:
            return SavedConfig.model_validate_json(row[0])
        except ValueError:
            return None

    def projects(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT project FROM test_configs ORDER BY project"
            ).fetchall()
        return [r[0] for r in rows if self.load(r[0])]

    def save(self, project: str, apps: list[AppSpec], card_key: str) -> SavedConfig:
        config = SavedConfig(
            project=project, apps=apps, saved_from=card_key, saved_at=_now()
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO test_configs (project, data) VALUES (?, ?) "
                "ON CONFLICT(project) DO UPDATE SET data = excluded.data",
                (self._check(project), config.model_dump_json()),
            )
        return config

    def delete(self, project: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM test_configs WHERE project = ?", (self._check(project),)
            )
        return cur.rowcount > 0


def project_of(card_key: str) -> str:
    return card_key.rsplit("-", 1)[0]


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


def load_fix_skill() -> str:
    return skills.strip_frontmatter(skills.read("testfix"))


def app_logs(store: TestStore, run: TestRun | None) -> str:
    """The log tail of each app of a previous run, for the fixing AI."""
    if run is None:
        return "(no previous run)"
    parts = []
    for i, spec in enumerate(run.apps):
        tail = log_tail(store.log_path(run, i)) or "(empty)"
        parts.append(f"--- log of '{spec.name}' (last lines) ---\n{tail}")
    if run.error:
        parts.append(f"--- error recorded for the run ---\n{run.error}")
    return "\n\n".join(parts) or "(no apps were started)"


def build_fix_prompt(
    card: Card,
    impl: Implementation,
    apps: list[AppSpec],
    problem: str,
    logs: str,
    skill: str | None = None,
) -> str:
    return "\n".join(
        [
            skills.AGENTS_PREAMBLE,
            "",
            skill if skill is not None else load_fix_skill(),
            "",
            f"Card: {card.key} - {card.summary}",
            f"Current branch (already checked out): {impl.branch}",
            "",
            "Current run settings (JSON):",
            json.dumps([a.model_dump(exclude_none=True) for a in apps], indent=2),
            "",
            "Problem reported by the user:",
            problem,
            "",
            "Output of the apps from the last attempt:",
            logs,
        ]
    )


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


async def stop_all(store: TestStore) -> None:
    for key in list(APPS):
        await stop_app(store, key)


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


def saved_links(apps: list[AppSpec], previous: TestRun | None) -> list[TestLink]:
    """Without the AI there is nothing new to say about what to check, so reuse the
    card's earlier links and add each app's own URL."""
    links = list(previous.links) if previous else []
    seen = {link.url for link in links}
    for spec in apps:
        if spec.ready_url not in seen:
            links.append(TestLink(title=f"{spec.name} app", url=spec.ready_url))
            seen.add(spec.ready_url)
    return links


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
    *,
    configs: ConfigStore | None = None,
    saved: list[AppSpec] | None = None,
    problem: str | None = None,
    previous: TestRun | None = None,
) -> None:
    """Start the card's branch for manual testing and wait until it responds.

    The apps come from the project's saved settings (`saved`, no AI), from the AI, or
    from the AI fixing the settings after the user reported a `problem`.

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

        if saved is not None and problem is None:
            apps, links, summary = saved, saved_links(saved, previous), None
            run.notes.append("Started with the project's saved settings (no AI used).")
        else:
            if problem is not None:
                fix_apps = (previous.apps if previous else []) or saved or []
                prompt = build_fix_prompt(
                    card, impl, fix_apps, problem, app_logs(store, previous)
                )
            else:
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
                run.notes.append(
                    "Some changes were left uncommitted in the working tree."
                )
            parsed = parse_output(output)
            apps, links, summary = parsed.apps, parsed.links, parsed.summary or None

        workdirs = [resolve_workdir(repo, a.workdir) for a in apps]
        run.apps, run.links, run.report = apps, links, summary
        store.save(run)

        running = Running(repo, [], [])
        APPS[run.card_key] = running
        for i, (spec, workdir) in enumerate(zip(apps, workdirs, strict=True)):
            log = store.log_path(run, i)
            if await probe(spec.ready_url):
                raise TesterError(
                    f"{spec.ready_url} already responds before the '{spec.name}' app "
                    "started, so its port is in use by another process. Stop that "
                    "process and try again."
                )
            wait = spec.ready_timeout_seconds or ready_timeout
            process = await spawner(spec.start_command, workdir, log)
            running.processes.append((spec.name, process))
            if not await wait_ready(process, spec.ready_url, wait, probe):
                why = (
                    f"The '{spec.name}' app exited (code {process.returncode})"
                    if process.returncode is not None
                    else f"The '{spec.name}' app did not respond at {spec.ready_url} "
                    f"within {int(wait)}s"
                )
                raise TesterError(f"{why}.\n{log_tail(log)}".strip())
        run.state = "running"
        store.save(run)
        if configs is not None:
            configs.save(project_of(run.card_key), apps, run.card_key)
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
