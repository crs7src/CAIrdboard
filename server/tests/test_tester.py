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
    monkeypatch.setenv("TEST_CONFIGS_DIR", str(env[0] / "test_configs"))
    for active in (implementer.ACTIVE, implementer.ACTIVE_REPOS, reviewer.ACTIVE):
        active.clear()
    yield
    tester.ACTIVE.clear()
    tester.APPS.clear()


async def run_it(tmp_path, work, ai, ready_timeout=15, **kw):
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
        ready_timeout, ai, **kw,
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
    assert client.post("/api/cards/AB-1/test", json={"use_ai": True}).status_code == 202
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
            assert (
                c.post("/api/cards/AB-1/test", json={"use_ai": True}).status_code == 202
            )
            assert c.get("/api/cards/AB-1/test").json()["state"] == "running"
    assert not tester.APPS
    with socket.socket() as s:
        assert s.connect_ex(("127.0.0.1", port)) != 0


async def test_port_already_in_use_fails_before_starting(env):
    tmp_path, work = env
    port = free_port()
    squatter = await asyncio.create_subprocess_exec(
        "python3", "-m", "http.server", str(port), "--bind", "127.0.0.1",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    try:
        for _ in range(50):
            if await tester.probe_url(f"http://localhost:{port}/"):
                break
            await asyncio.sleep(0.1)
        _, run = await run_it(tmp_path, work, FakeTester(reply(port)))
        assert run.state == "failed" and "port is in use" in run.error
        assert not tester.APPS
    finally:
        squatter.kill()
        await squatter.wait()


async def test_per_app_ready_timeout_overrides_the_default(env):
    tmp_path, work = env
    port = free_port()
    slow = app_spec(
        port,
        start_command=f"sleep 2; python3 -m http.server {port} --bind 127.0.0.1",
        ready_timeout_seconds=20,
    )
    store, run = await run_it(
        tmp_path, work, FakeTester(reply(port, apps=[slow])), ready_timeout=1
    )
    try:
        assert run.state == "running", run.error
    finally:
        await tester.stop_app(store, "AB-1")


def test_ready_timeout_is_bounded():
    with pytest.raises(ValueError):
        tester.AppSpec(
            start_command="x",
            ready_url="http://localhost:1/",
            ready_timeout_seconds=100000,
        )


class NoAi:
    """Fails the test if the AI is called."""

    async def __call__(self, args, cwd, timeout):
        if args[0] == "git":
            return await run_command(args, cwd, timeout)
        raise AssertionError("the AI must not be used")


def prompt_of(ai):
    args = ai.ai_calls[-1]
    return args[args.index("-p") + 1]


async def test_successful_run_saves_the_settings_per_project(env):
    tmp_path, work = env
    port = free_port()
    configs = tester.ConfigStore(tmp_path / "test_configs")
    store, run = await run_it(tmp_path, work, FakeTester(reply(port)), configs=configs)
    try:
        assert run.state == "running", run.error
        saved = configs.load("AB")
        assert saved.saved_from == "AB-1"
        assert [a.start_command for a in saved.apps] == [run.apps[0].start_command]
    finally:
        await tester.stop_app(store, "AB-1")


async def test_failed_run_does_not_save(env):
    tmp_path, work = env
    configs = tester.ConfigStore(tmp_path / "test_configs")
    _, run = await run_it(
        tmp_path, work, FakeTester(reply(1, start_command="exit 1")),
        ready_timeout=3, configs=configs,
    )  # fmt: skip
    assert run.state == "failed" and configs.load("AB") is None


async def test_saved_settings_start_without_the_ai(env):
    tmp_path, work = env
    port = free_port()
    saved = [tester.AppSpec(**app_spec(port))]
    configs = tester.ConfigStore(tmp_path / "test_configs")
    store, run = await run_it(tmp_path, work, NoAi(), configs=configs, saved=saved)
    try:
        assert run.state == "running", run.error
        assert any("saved settings" in n for n in run.notes)
        assert [link.url for link in run.links] == [f"http://localhost:{port}/"]
    finally:
        await tester.stop_app(store, "AB-1")


async def test_saved_links_reuse_the_previous_runs_links(env):
    link = tester.TestLink(title="Old", url="http://localhost:9/x", check="c")
    app = tester.AppSpec(**app_spec(7))
    previous = tester.TestRun(
        card_key="AB-1", version=1, state="stopped", links=[link],
        created_at="t", updated_at="t",
    )  # fmt: skip
    links = tester.saved_links([app], previous)
    assert [x.url for x in links] == ["http://localhost:9/x", "http://localhost:7/"]
    assert tester.saved_links([app], None)[0].title == "app app"


async def test_failed_saved_start_keeps_the_saved_settings(env):
    tmp_path, work = env
    configs = tester.ConfigStore(tmp_path / "test_configs")
    saved = [tester.AppSpec(**app_spec(1, start_command="exit 1"))]
    configs.save("AB", saved, "AB-1")
    _, run = await run_it(
        tmp_path, work, NoAi(), ready_timeout=3, configs=configs, saved=saved
    )
    assert run.state == "failed"
    assert configs.load("AB") is not None


async def test_problem_prompt_has_the_report_settings_and_logs_and_saves_the_fix(env):
    tmp_path, work = env
    port = free_port()
    store = tester.TestStore(tmp_path / "test_runs")
    impl = make_impl(tmp_path, work)
    old = store.create("AB-1", impl, 1)
    old.state, old.error = "failed", "boom"
    old.apps = [tester.AppSpec(**app_spec(1, "api", start_command="old-cmd"))]
    store.save(old)
    store.log_path(old, 0).write_text("line one\nOOPS-LOG-LINE\n")

    configs = tester.ConfigStore(tmp_path / "test_configs")
    ai = FakeTester(reply(port))
    run = store.create("AB-1", impl, 1, "feedback", "the API never starts")
    tester.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await tester.run_test(
        store, run, impl, make_card(), "1. Do it", str(work), "copilot", 60, 15, ai,
        configs=configs, problem="the API never starts", previous=old,
    )  # fmt: skip
    try:
        run = store.latest("AB-1")
        assert run.state == "running", run.error
        prompt = prompt_of(ai)
        assert "the API never starts" in prompt
        assert "OOPS-LOG-LINE" in prompt and "old-cmd" in prompt
        assert "shell(git push)" in ai.ai_calls[0]
        assert configs.load("AB").apps[0].ready_url == f"http://localhost:{port}/"
    finally:
        await tester.stop_app(store, "AB-1")


def test_config_store_round_trip_and_rejects_bad_projects(tmp_path):
    configs = tester.ConfigStore(tmp_path)
    assert configs.load("AB") is None
    configs.save("AB", [tester.AppSpec(**app_spec(5))], "AB-1")
    assert configs.load("AB").apps[0].name == "app"
    assert configs.delete("AB") and not configs.delete("AB")
    with pytest.raises(ValueError):
        configs.load("../x")


@respx.mock
def test_api_uses_saved_settings_then_replan_uses_the_ai(client, env, ai):
    tmp_path, work = env
    mock_jira()
    allow_local()
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    make_review(tmp_path, impl)
    port = free_port()
    ai.stdout = reply(port)
    assert client.get("/api/cards/AB-1/test/config").status_code == 404
    tester.ConfigStore(tmp_path / "test_configs").save(
        "AB", [tester.AppSpec(**app_spec(port))], "AB-9"
    )
    assert client.get("/api/cards/AB-1/test/config").json()["saved_from"] == "AB-9"

    assert client.post("/api/cards/AB-1/test").json()["source"] == "saved"
    body = client.get("/api/cards/AB-1/test").json()
    assert body["state"] == "running", body["error"]
    assert ai.ai_calls == []
    assert client.delete("/api/cards/AB-1/test").status_code == 200

    assert (
        client.post("/api/cards/AB-1/test", json={"use_ai": True}).json()["source"]
        == "ai"
    )
    assert client.get("/api/cards/AB-1/test").json()["state"] == "running"
    assert len(ai.ai_calls) == 1
    client.delete("/api/cards/AB-1/test")

    assert client.delete("/api/cards/AB-1/test/config").status_code == 204
    assert client.get("/api/cards/AB-1/test/config").status_code == 404


@respx.mock
def test_api_problem_report_restarts_with_the_fixed_settings(client, env, ai):
    tmp_path, work = env
    mock_jira()
    allow_local()
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    make_review(tmp_path, impl)
    assert (
        client.post("/api/cards/AB-1/test/problem", json={"message": "x"}).status_code
        == 409
    )
    port = free_port()
    ai.stdout = reply(port)
    client.post("/api/cards/AB-1/test", json={"use_ai": True})
    assert client.get("/api/cards/AB-1/test").json()["state"] == "running"

    assert (
        client.post("/api/cards/AB-1/test/problem", json={"message": " "}).status_code
        == 422
    )
    r = client.post("/api/cards/AB-1/test/problem", json={"message": "login is blank"})
    assert r.status_code == 202
    body = client.get("/api/cards/AB-1/test").json()
    assert body["state"] == "running", body["error"]
    assert body["source"] == "feedback" and body["problem"] == "login is blank"
    assert body["version"] == 2
    assert "login is blank" in prompt_of(ai)
    client.delete("/api/cards/AB-1/test")
    assert str(work) not in implementer.ACTIVE_REPOS


@respx.mock
def test_start_without_configured_settings_is_refused_and_never_uses_the_ai(
    client, env, ai
):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    make_review(tmp_path, impl)
    r = client.post("/api/cards/AB-1/test")
    assert r.status_code == 409 and "Test apps" in r.json()["detail"]
    assert ai.ai_calls == [] and not tester.ACTIVE
    assert client.get("/api/cards/AB-1/test").status_code == 404


def test_project_settings_can_be_set_read_and_cleared(client, env):
    _tmp_path, work = env
    (work / "web").mkdir()
    apps = [
        app_spec(5, "api", start_command="run api"),
        app_spec(6, "web", workdir="web", ready_timeout_seconds=120),
    ]
    assert client.get("/api/test-configs/AB").status_code == 404
    r = client.put("/api/test-configs/AB", json={"apps": apps})
    assert r.status_code == 200 and r.json()["saved_from"] == "settings"
    body = client.get("/api/test-configs/AB").json()
    assert [a["name"] for a in body["apps"]] == ["api", "web"]
    assert body["apps"][1]["ready_timeout_seconds"] == 120
    assert client.delete("/api/test-configs/AB").status_code == 204
    assert client.get("/api/test-configs/AB").status_code == 404


@pytest.mark.parametrize(
    "apps",
    [
        [],
        [app_spec(1, "a"), app_spec(2, "a")],
        [app_spec(1, ready_url="http://example.com/")],
        [app_spec(1, start_command=" ")],
        [app_spec(1, workdir="../..")],
        [app_spec(1, workdir="missing")],
    ],
)
def test_invalid_project_settings_are_rejected(client, env, apps):
    assert client.put("/api/test-configs/AB", json={"apps": apps}).status_code == 422
    assert client.get("/api/test-configs/AB").status_code == 404


def test_settings_need_a_project_with_a_repo(client):
    assert client.get("/api/test-configs/ZZ").status_code == 404
    r = client.put("/api/test-configs/ZZ", json={"apps": [app_spec(1)]})
    assert r.status_code == 404
    assert client.put("/api/test-configs/..%2Fx", json={"apps": []}).status_code == 404
