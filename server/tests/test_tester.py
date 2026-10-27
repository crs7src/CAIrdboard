# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
import asyncio
import json
import socket
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from test_implementation import (
    approve_plan,
    env,
    make_card,
    mock_jira,
    repos,
    sh,
)
from test_review import make_impl

from app import implementer, reviewer, tester
from app.main import app, get_runner
from app.planner import CommandResult, run_command


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def app_spec(port, name="app", **over):
    return {
        "name": name,
        "start_command": f"python3 -m http.server {port} --bind 127.0.0.1",
        "workdir": ".",
        "ready_url": f"http://localhost:{port}/",
        **over,
    }


def reply(port, apps=None, **overrides):
    """Overrides for start_command/workdir/ready_url change the single app."""
    app_over = {
        k: overrides.pop(k)
        for k in ("start_command", "workdir", "ready_url")
        if k in overrides
    }
    out = {
        "apps": apps if apps is not None else [app_spec(port, **app_over)],
        "links": [
            {
                "title": "Toggle",
                "url": f"http://localhost:{port}/settings",
                "check": "Flip it",
            }
        ],
        "summary": "Dark mode",
    }
    out.update(overrides)
    return "I checked it.\n```json\n" + json.dumps(out) + "\n```\n"


def legacy_reply(port):
    out = {k: v for k, v in app_spec(port).items() if k != "name"}
    out |= {"links": [{"title": "T", "url": f"http://localhost:{port}/"}]}
    return "```json\n" + json.dumps(out) + "\n```"


class FakeTester:
    def __init__(self, stdout, returncode=0, stderr="", switch_branch=False):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.switch_branch = switch_branch
        self.ai_calls: list[list[str]] = []

    async def __call__(self, args, cwd, timeout):
        if args[0] == "git":
            return await run_command(args, cwd, timeout)
        self.ai_calls.append(args)
        if self.switch_branch:
            sh(Path(cwd), "git", "checkout", "-q", "main")
        return CommandResult(self.returncode, self.stdout, self.stderr)


@pytest.fixture(autouse=True)
def dirs(env, monkeypatch):
    monkeypatch.setenv("TEST_RUNS_DIR", str(env[0] / "test_runs"))
    monkeypatch.setenv("REVIEWS_DIR", str(env[0] / "reviews"))
    for active in (implementer.ACTIVE, implementer.ACTIVE_REPOS, reviewer.ACTIVE):
        active.clear()
    yield
    tester.ACTIVE.clear()
    tester.APPS.clear()


async def run_it(tmp_path, work, ai, ready_timeout=15):
    if sh(work, "git", "branch", "--list", "AB-1_add_dark_mode"):
        impl = implementer.ImplementationStore(tmp_path / "impls").latest("AB-1")
    else:
        impl = make_impl(tmp_path, work)
    store = tester.TestStore(tmp_path / "test_runs")
    run = store.create("AB-1", impl, 1)
    tester.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await tester.run_test(
        store, run, impl, make_card(), "1. Do it", str(work), "copilot", 60,
        ready_timeout, ai,
    )  # fmt: skip
    return store, store.latest("AB-1")


async def test_app_is_started_and_kept_running_until_stopped(env):
    tmp_path, work = env
    port = free_port()
    ai = FakeTester(reply(port))
    store, run = await run_it(tmp_path, work, ai)
    try:
        assert run.state == "running", run.error
        assert run.links[0].title == "Toggle"
        assert (
            sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == "AB-1_add_dark_mode"
        )
        assert "AB-1" in tester.ACTIVE and str(work) in implementer.ACTIVE_REPOS
        assert await tester.probe_url(run.apps[0].ready_url)
        prompt = ai.ai_calls[0][ai.ai_calls[0].index("-p") + 1]
        assert "AB-1 - Add a dark mode toggle" in prompt
        assert "shell(git push)" in ai.ai_calls[0]
    finally:
        stopped = await tester.stop_app(store, "AB-1")
    assert stopped.state == "stopped"
    assert not await tester.probe_url(run.apps[0].ready_url)
    assert "AB-1" not in tester.ACTIVE
    assert str(work) not in implementer.ACTIVE_REPOS


async def test_several_apps_are_started_in_order_and_all_stopped(env):
    tmp_path, work = env
    api, web = free_port(), free_port()
    out = reply(
        web,
        apps=[app_spec(api, "api"), app_spec(web, "web")],
    )
    store, run = await run_it(tmp_path, work, FakeTester(out))
    try:
        assert run.state == "running", run.error
        assert [a.name for a in run.apps] == ["api", "web"]
        assert await tester.probe_url(f"http://localhost:{api}/")
        assert await tester.probe_url(f"http://localhost:{web}/")
        assert len(tester.APPS["AB-1"].processes) == 2
    finally:
        await tester.stop_app(store, "AB-1")
    assert not await tester.probe_url(f"http://localhost:{api}/")
    assert not await tester.probe_url(f"http://localhost:{web}/")
    assert not tester.APPS and str(work) not in implementer.ACTIVE_REPOS


async def test_second_app_failing_stops_the_first(env):
    tmp_path, work = env
    api, web = free_port(), free_port()
    out = reply(
        web,
        apps=[app_spec(api, "api"), app_spec(web, "web", start_command="exit 2")],
    )
    _, run = await run_it(tmp_path, work, FakeTester(out), ready_timeout=5)
    assert run.state == "failed" and "'web' app exited (code 2)" in run.error
    assert not await tester.probe_url(f"http://localhost:{api}/")
    assert not tester.APPS and "AB-1" not in tester.ACTIVE


async def test_one_app_exiting_stops_the_others(env):
    tmp_path, work = env
    api, web = free_port(), free_port()
    out = reply(
        web,
        apps=[
            app_spec(api, "api"),
            app_spec(
                web,
                "web",
                start_command=f"sleep 1; python3 -m http.server {web} --bind 127.0.0.1",
            ),
        ],
    )
    store, run = await run_it(tmp_path, work, FakeTester(out))
    assert run.state == "running", run.error
    running = tester.APPS["AB-1"]
    _, api_proc = running.processes[0]
    api_proc.terminate()
    for _ in range(100):
        if "AB-1" not in tester.APPS:
            break
        await asyncio.sleep(0.1)
    assert not tester.APPS and str(work) not in implementer.ACTIVE_REPOS
    saved = store.latest("AB-1")
    assert saved.state == "stopped" and "'api' app exited" in saved.notes[-1]
    assert not await tester.probe_url(f"http://localhost:{web}/")


def test_old_single_app_format_is_accepted_and_migrated(tmp_path):
    out = tester.parse_output(legacy_reply(1234))
    assert [a.name for a in out.apps] == ["app"]
    assert out.apps[0].ready_url == "http://localhost:1234/"
    old = {
        "card_key": "AB-1", "version": 1, "state": "stopped", "start_command": "x",
        "workdir": ".", "ready_url": "http://localhost:1/", "created_at": "t", "updated_at": "t",
    }  # fmt: skip
    assert tester.TestRun.model_validate(old).apps[0].start_command == "x"


async def test_app_exiting_on_its_own_is_recorded(env):
    tmp_path, work = env
    port = free_port()
    out = reply(port, start_command="exit 3", ready_url=f"http://localhost:{port}/")
    _, run = await run_it(tmp_path, work, FakeTester(out), ready_timeout=5)
    assert run.state == "failed" and "exited (code 3)" in run.error
    assert str(work) not in implementer.ACTIVE_REPOS


async def test_app_that_never_responds_fails_and_is_killed(env):
    tmp_path, work = env
    port = free_port()
    out = reply(port, start_command="sleep 30")
    _, run = await run_it(tmp_path, work, FakeTester(out), ready_timeout=1)
    assert run.state == "failed" and "did not respond" in run.error
    assert "AB-1" not in tester.ACTIVE and not tester.APPS


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("no block here", "no JSON block"),
        ("```json\n{not json}\n```", "invalid"),
        (reply(1, ready_url="http://example.com/"), "not a local"),
        (reply(1, workdir="../.."), "outside the repo"),
        (reply(1, workdir="nope"), "does not exist"),
        (reply(1, start_command="  "), "empty"),
        (reply(1, apps=[]), "at least 1"),
        (reply(1, apps=[app_spec(1, "a"), app_spec(2, "a")]), "unique"),
    ],
)
async def test_bad_ai_output_fails_without_starting_anything(env, stdout, message):
    tmp_path, work = env
    _, run = await run_it(tmp_path, work, FakeTester(stdout))
    assert run.state == "failed" and message in run.error
    assert not tester.APPS and str(work) not in implementer.ACTIVE_REPOS


async def test_ai_failures_and_branch_switch_are_recorded(env):
    tmp_path, work = env
    _, run = await run_it(tmp_path, work, FakeTester("", 1, "boom"))
    assert run.state == "failed" and "boom" in run.error
    _, run = await run_it(tmp_path, work, FakeTester(reply(1), switch_branch=True))
    assert run.state == "failed" and "left the branch" in run.error


async def test_dirty_repo_is_refused(env):
    tmp_path, work = env
    (work / "dirty.txt").write_text("x")
    _, run = await run_it(tmp_path, work, FakeTester(reply(1)))
    assert run.state == "failed" and "uncommitted" in run.error


def test_stale_runs_are_recovered(tmp_path):
    store = tester.TestStore(tmp_path)
    impl = implementer.Implementation(
        card_key="AB-1", version=1, plan_version=1, state="completed",
        branch="b", base_commit="a", created_at="t", updated_at="t",
    )  # fmt: skip
    run = store.create("AB-1", impl, 1)
    assert tester.recover_stale(store, run).state == "failed"
    run = store.create("AB-1", impl, 1)
    run.state = "running"
    assert tester.recover_stale(store, run).state == "stopped"


@pytest.fixture
def ai():
    fake = FakeTester(reply(free_port()))
    app.dependency_overrides[get_runner] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(env, ai):
    with TestClient(app) as c:
        yield c


def allow_local():
    respx.route(host="localhost").pass_through()


def make_review(tmp_path, impl, state="clean"):
    store = reviewer.ReviewStore(tmp_path / "reviews")
    run = store.create("AB-1", impl)
    run.state = state
    store.save(run)


@respx.mock
def test_start_requires_a_clean_review(client, env):
    tmp_path, work = env
    mock_jira()
    allow_local()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/test").status_code == 409
    impl = make_impl(tmp_path, work)
    assert client.post("/api/cards/AB-1/test").status_code == 409
    make_review(tmp_path, impl, "fixed")
    assert client.post("/api/cards/AB-1/test").status_code == 409


@respx.mock
def test_start_get_list_and_stop(client, env, ai):
    tmp_path, work = env
    mock_jira()
    allow_local()
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    make_review(tmp_path, impl)
    assert client.get("/api/cards/AB-1/test").status_code == 404
    assert client.post("/api/cards/AB-1/test").status_code == 202
    body = client.get("/api/cards/AB-1/test").json()
    assert body["state"] == "running", body["error"]
    assert client.get("/api/tests").json() == {"AB-1": "running"}
    assert client.post("/api/cards/AB-1/test").status_code == 409
    stopped = client.delete("/api/cards/AB-1/test")
    assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
    assert client.get("/api/tests").json() == {"AB-1": "stopped"}
    assert str(work) not in implementer.ACTIVE_REPOS


@respx.mock
def test_start_conflicts_when_repo_busy(client, env):
    tmp_path, work = env
    mock_jira()
    allow_local()
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    make_review(tmp_path, impl)
    implementer.ACTIVE_REPOS.add(str(work))
    assert client.post("/api/cards/AB-1/test").status_code == 409
    implementer.ACTIVE_REPOS.clear()


def test_server_shutdown_stops_running_apps(env, ai):
    tmp_path, work = env
    port = free_port()
    ai.stdout = reply(port)
    with respx.mock:
        mock_jira()
        allow_local()
        approve_plan(tmp_path)
        impl = make_impl(tmp_path, work)
        make_review(tmp_path, impl)
        with TestClient(app) as c:
            assert c.post("/api/cards/AB-1/test").status_code == 202
            assert c.get("/api/cards/AB-1/test").json()["state"] == "running"
    assert not tester.APPS
    with socket.socket() as s:
        assert s.connect_ex(("127.0.0.1", port)) != 0
