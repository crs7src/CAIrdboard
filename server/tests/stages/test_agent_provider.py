# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
from pathlib import Path

from dbutil import db
from test_feedback import FakeEditor
from test_implementation import (
    commit_file,
    env,
    make_card,
    repos,
    sh,
)
from test_review import BRANCH, make_impl

from app.stages import feedback, implementer, reviewer
from app.stages.planner import CommandResult, run_command


class FakeAgentProvider:
    """Stands in for an API provider: real git, commits made by the 'model'."""

    id = "anthropic"
    label = "Anthropic"

    def __init__(self, commit_name, message):
        self.commit_name, self.message = commit_name, message
        self.calls = []

    async def run(self, prompt, cwd, timeout, mode="plan"):
        self.calls.append((prompt, cwd, timeout, mode))
        if mode == "summary":
            return CommandResult(0, "add dark mode", "")
        commit_file(Path(cwd), self.commit_name, self.message)
        return CommandResult(0, "## Report\nok", "")


class NoCopilot:
    """A runner that does git but fails if the Copilot CLI is invoked."""

    async def __call__(self, args, cwd, timeout):
        assert args[0] == "git", f"unexpected AI command: {args}"
        return await run_command(args, cwd, timeout)


async def test_implementer_runs_on_the_provider_in_agent_mode(env):
    _, work = env
    provider = FakeAgentProvider("f1.txt", "AB-1: step 1 - toggle")
    store = implementer.ImplementationStore(db())
    run = store.create("AB-1", 1)
    implementer.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await implementer.run_implementation(
        store,
        run,
        make_card(),
        "1. Do it",
        str(work),
        "copilot",
        60,
        NoCopilot(),
        provider,
        provider,
    )
    done = store.latest("AB-1")
    assert done.state == "completed", done.error
    assert done.provider == "anthropic"
    assert done.branch == "AB-1_add_dark_mode"
    assert [c[3] for c in provider.calls] == ["summary", "agent"]
    assert "Approved plan to implement" in provider.calls[1][0]
    assert provider.calls[1][1] == str(work)


async def test_provider_leaving_the_branch_still_fails_the_run(env):
    _, work = env

    class Wanderer(FakeAgentProvider):
        async def run(self, prompt, cwd, timeout, mode="plan"):
            result = await super().run(prompt, cwd, timeout, mode)
            if mode == "agent":
                sh(Path(cwd), "git", "checkout", "-q", "main")
            return result

    provider = Wanderer("f1.txt", "AB-1: step 1 - toggle")
    store = implementer.ImplementationStore(db())
    run = store.create("AB-1", 1)
    implementer.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await implementer.run_implementation(
        store,
        run,
        make_card(),
        "1.",
        str(work),
        "copilot",
        60,
        NoCopilot(),
        provider,
        provider,
    )
    assert "left the branch" in store.latest("AB-1").error


async def test_reviewer_and_feedback_run_on_the_provider(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)

    provider = FakeAgentProvider("fix1.txt", "AB-1: review fix - null check")
    store = reviewer.ReviewStore(db())
    run = store.create("AB-1", impl)
    reviewer.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await reviewer.run_review(
        store,
        run,
        impl,
        make_card(),
        "1. Do it",
        str(work),
        "copilot",
        60,
        NoCopilot(),
        provider,
    )
    review = store.latest("AB-1")
    assert review.state == "fixed", review.error
    assert review.provider == "anthropic"
    assert provider.calls[0][3] == "agent"

    provider = FakeAgentProvider("fb1.txt", "AB-1: address feedback - rename")
    fstore = feedback.FeedbackStore(db())
    fstore.add("AB-1", feedback.CommentInput(text="rename it"))
    frun = fstore.create("AB-1", impl)
    feedback.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await feedback.run_feedback(
        fstore,
        frun,
        impl,
        make_card(),
        "1. Do it",
        str(work),
        "copilot",
        60,
        NoCopilot(),
        provider,
    )
    done = fstore.latest("AB-1")
    assert done.state == "done", done.error
    assert done.provider == "anthropic"
    assert [c.subject for c in done.commits] == ["AB-1: address feedback - rename"]
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
