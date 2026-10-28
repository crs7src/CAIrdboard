from datetime import UTC, datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from app import hosting
from app.config import Settings
from app.db import RunStore
from app.implementer import Implementation, ImplementationError, _git
from app.jira import Card
from app.remotes import HostError

PUSH_TIMEOUT = 300

# running: pushing / creating; created: the branch is pushed and the MR exists
# (a push to an existing MR also ends here); failed: the run broke.
MrState = Literal["running", "created", "failed"]


class MergeRequest(BaseModel):
    card_key: str
    version: int
    implementation_version: int
    state: MrState
    branch: str
    target_branch: str
    title: str
    provider: hosting.Provider = "gitlab"
    # Runs stored before GitHub support called this gitlab_project.
    host_project: str = Field(
        validation_alias=AliasChoices("host_project", "gitlab_project")
    )
    head: str | None = None
    mr_iid: int | None = None
    mr_url: str | None = None
    # True when the branch was pushed to an MR that already existed.
    updated_existing: bool = False
    error: str | None = None
    created_at: str
    updated_at: str
    # Not stored: the branch has moved on since the push.
    outdated: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def title_for(branch: str) -> str:
    return branch.replace("_", " ")


class MergeRequestStore(RunStore[MergeRequest]):
    kind = "mr"
    model = MergeRequest

    def create(
        self,
        key: str,
        impl: Implementation,
        provider: hosting.Provider,
        host_project: str,
    ):
        branch = impl.branch or ""

        def build(version: int, stamp: str):
            return MergeRequest(
                card_key=key,
                version=version,
                implementation_version=impl.version,
                state="running",
                branch=branch,
                target_branch=impl.base_branch or "main",
                title=title_for(branch),
                provider=provider,
                host_project=host_project,
                created_at=stamp,
                updated_at=stamp,
            )

        return self.create_run(key, build)


# Card keys with a merge request being created in this server process.
ACTIVE: set[str] = set()


def recover_stale(
    store: MergeRequestStore, run: MergeRequest | None
) -> MergeRequest | None:
    if run and run.state == "running" and run.card_key not in ACTIVE:
        run.state = "failed"
        run.error = "Interrupted before it finished. Try again."
        store.save(run)
    return run


async def branch_head(runner, repo: str, branch: str) -> str | None:
    try:
        return await _git(runner, repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    except ImplementationError:
        return None


async def mark_outdated(runner, repo: str | None, run: MergeRequest | None) -> None:
    """Flag a created MR whose branch has new commits since it was pushed."""
    if run is None or run.state != "created" or repo is None:
        return
    head = await branch_head(runner, repo, run.branch)
    run.outdated = head is not None and head != run.head


def closing_line(card: Card, provider: str, host_project: str) -> str | None:
    """Lets GitHub close the issue when its pull request merges."""
    if card.source != "github" or provider != "github" or not card.external_repo:
        return None
    number = card.key.rsplit("-", 1)[1]
    if card.external_repo.lower() == host_project.lower():
        return f"Closes #{number}"
    return f"Closes {card.external_repo}#{number}"


async def build_description(
    runner,
    repo: str,
    impl: Implementation,
    branch: str,
    card: Card,
    closes: str | None = None,
) -> str:
    lines = [f"[{card.key}]({card.url}):"]
    if closes:
        lines += ["", closes]
    if impl.base_commit:
        out = await _git(
            runner,
            repo,
            "log",
            "--reverse",
            "--format=%s",
            f"{impl.base_commit}..refs/heads/{branch}",
        )
        subjects = [s for s in out.splitlines() if s]
        if subjects:
            lines += ["", "Commits:", *(f"- {s}" for s in subjects)]
    return "\n".join(lines)


async def resolve_target(
    runner, repo: str, settings: Settings, run: MergeRequest
) -> None:
    """Make sure the target branch exists on origin; branches continued from an earlier
    run have no recorded base, and a local base may never have been pushed."""
    ref = f"refs/heads/{run.target_branch}"
    if await _git(runner, repo, "ls-remote", "--heads", "origin", ref):
        return
    project = await hosting.fetch_project(settings, run.provider, run.host_project)
    if not project.default_branch:
        raise ImplementationError(
            f"Branch '{run.target_branch}' is not on origin and the default branch is unknown"
        )
    run.target_branch = project.default_branch


async def run_merge_request(
    store: MergeRequestStore,
    run: MergeRequest,
    impl: Implementation,
    card: Card,
    repo: str,
    settings: Settings,
    runner,
) -> None:
    """Push the card's branch to origin and open (or reuse) its merge request. Never raises."""
    try:
        run.head = await branch_head(runner, repo, run.branch)
        if run.head is None:
            raise ImplementationError(f"Branch '{run.branch}' no longer exists")
        store.save(run)
        # A plain push: it is rejected rather than overwriting anything on origin.
        await _git(
            runner,
            repo,
            "push",
            "-u",
            "origin",
            f"refs/heads/{run.branch}:refs/heads/{run.branch}",
            timeout=PUSH_TIMEOUT,
        )
        existing = await hosting.find_open(
            settings, run.provider, run.host_project, run.branch
        )
        if existing:
            mr, run.updated_existing = existing, True
        else:
            await resolve_target(runner, repo, settings, run)
            store.save(run)
            description = await build_description(
                runner,
                repo,
                impl,
                run.branch,
                card,
                closing_line(card, run.provider, run.host_project),
            )
            mr = await hosting.create(
                settings,
                run.provider,
                run.host_project,
                run.branch,
                run.target_branch,
                run.title,
                description,
            )
        run.mr_iid, run.mr_url, run.state = mr.iid, mr.web_url, "created"
    except (ImplementationError, HostError) as e:
        run.state, run.error = "failed", str(e)
    except Exception as e:  # noqa: BLE001 - record any failure on the run
        run.state, run.error = "failed", f"Unexpected error: {e}"
    finally:
        ACTIVE.discard(run.card_key)
        store.save(run)
