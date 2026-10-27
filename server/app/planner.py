import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.jira import Card

PlanState = Literal["running", "ready", "failed", "approved", "rejected"]

CARD_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

# Planning must never change the target repo: only file-reading tools are exposed.
READ_ONLY_TOOLS = ["view", "grep", "glob"]


class Plan(BaseModel):
    card_key: str
    version: int
    state: PlanState
    jira_status: str
    feedback: str | None = None
    plan: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandTimeout(Exception):
    pass


class CommandNotFound(Exception):
    pass


async def run_command(args: list[str], cwd: str, timeout: float) -> CommandResult:
    """Run a command without a shell and capture its output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise CommandNotFound(args[0]) from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise CommandTimeout from e
    return CommandResult(proc.returncode or 0, out.decode(), err.decode())


def build_prompt(card: Card, previous: Plan | None, feedback: str | None) -> str:
    parts = [
        (
            "You are planning work on a Jira card in the repository in your current "
            "working directory. Explore the code with your read-only tools, then write "
            "an implementation plan. Do NOT modify any files and do NOT write code "
            "changes; output only the plan."
        ),
        "",
        f"Card: {card.key} - {card.summary}",
        f"Jira status: {card.status}",
        f"Priority: {card.priority or 'none'}",
        "",
        "Description:",
        card.description or "(no description)",
        "",
        (
            "Format the plan as Markdown with these sections: Summary, Files to "
            "change, Steps, Tests, Risks and open questions."
        ),
    ]
    if previous and previous.plan and feedback:
        parts += [
            "",
            "A previous plan was reviewed and the reviewer was not satisfied.",
            "Previous plan:",
            previous.plan,
            "",
            "Reviewer feedback to address in the new plan:",
            feedback,
        ]
    elif feedback:
        parts += ["", "Additional guidance from the reviewer:", feedback]
    return "\n".join(parts)


def build_args(command: str, prompt: str) -> list[str]:
    return [
        command,
        "-s",
        "-p",
        prompt,
        "--available-tools",
        *READ_ONLY_TOOLS,
        "--allow-tool",
        *READ_ONLY_TOOLS,
    ]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PlanStore:
    """One JSON file per plan version: <root>/<CARD-KEY>/<version>.json."""

    def __init__(self, root: Path):
        self.root = root

    def _dir(self, key: str) -> Path:
        if not CARD_KEY_RE.match(key):
            raise ValueError(f"Invalid card key: {key}")
        return self.root / key

    def versions(self, key: str) -> list[Plan]:
        d = self._dir(key)
        if not d.exists():
            return []
        plans = [Plan.model_validate_json(p.read_text()) for p in d.glob("*.json")]
        return sorted(plans, key=lambda p: p.version)

    def latest(self, key: str) -> Plan | None:
        plans = self.versions(key)
        return plans[-1] if plans else None

    def create(self, key: str, jira_status: str, feedback: str | None) -> Plan:
        latest = self.latest(key)
        now = _now()
        plan = Plan(
            card_key=key,
            version=(latest.version + 1) if latest else 1,
            state="running",
            jira_status=jira_status,
            feedback=feedback,
            created_at=now,
            updated_at=now,
        )
        self.save(plan)
        return plan

    def save(self, plan: Plan) -> Plan:
        plan.updated_at = _now()
        d = self._dir(plan.card_key)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{plan.version}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(plan.model_dump_json(indent=2))
        os.replace(tmp, path)
        return plan


# Card keys with a generation running in this server process. The caller adds
# the key before scheduling generate(), which removes it when finished.
ACTIVE: set[str] = set()


async def generate(
    store: PlanStore,
    plan: Plan,
    card: Card,
    previous: Plan | None,
    repo: str,
    command: str,
    timeout: float,
    runner=run_command,
) -> None:
    """Run the AI and record the outcome on the plan. Never raises."""
    try:
        prompt = build_prompt(card, previous, plan.feedback)
        result = await runner(build_args(command, prompt), repo, timeout)
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            plan.state = "failed"
            plan.error = (
                result.stderr.strip() or output or "The AI produced no output"
            )[:2000]
        else:
            plan.state, plan.plan = "ready", output
    except CommandTimeout:
        plan.state, plan.error = "failed", f"Timed out after {int(timeout)}s"
    except CommandNotFound:
        plan.state, plan.error = "failed", f"Command not found: {command}"
    except Exception as e:  # noqa: BLE001 - record any failure on the plan
        plan.state, plan.error = "failed", f"Unexpected error: {e}"
    finally:
        ACTIVE.discard(plan.card_key)
        store.save(plan)


def recover_stale(store: PlanStore, plan: Plan | None) -> Plan | None:
    """A 'running' plan with no live task was interrupted (e.g. server restart)."""
    if plan and plan.state == "running" and plan.card_key not in ACTIVE:
        plan.state = "failed"
        plan.error = "Interrupted before it finished. Regenerate the plan."
        store.save(plan)
    return plan
