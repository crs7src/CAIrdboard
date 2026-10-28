import json

import httpx
import pytest
import respx

from app.ai import tools
from app.ai.anthropic import AnthropicProvider
from app.ai.gemini import GeminiProvider
from app.ai.tools import ToolBox


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def hello():\n    return 1\n")
    (root / "README.md").write_text("# Title\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("hello secret")
    return root


def test_view_file_directory_and_range(repo):
    box = ToolBox(str(repo))
    assert box.call("view", {"path": "src/a.py"}) == "1. def hello():\n2.     return 1"
    assert box.call("view", {"path": "src/a.py", "start_line": 2, "end_line": 2}) == (
        "2.     return 1"
    )
    listing = box.call("view", {"path": "."}).splitlines()
    assert listing == ["src/", "README.md"]


def test_grep_and_glob_skip_git(repo):
    box = ToolBox(str(repo))
    assert box.call("grep", {"pattern": "hello"}) == "src/a.py:1:def hello():"
    assert box.call("grep", {"pattern": "zzz"}) == "No matches"
    assert box.call("grep", {"pattern": "hello", "glob": "*.md"}) == "No matches"
    assert box.call("glob", {"pattern": "**/*"}).splitlines() == [
        "README.md",
        "src",
        "src/a.py",
    ]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("view", {"path": "../outside.txt"}),
        ("view", {"path": "/etc/passwd"}),
        ("grep", {"pattern": "x", "path": ".."}),
        ("glob", {"pattern": "../*"}),
        ("glob", {"pattern": "/etc/*"}),
        ("rm", {"path": "x"}),
    ],
)
def test_escapes_and_unknown_tools_are_rejected(repo, name, args):
    assert ToolBox(str(repo)).call(name, args).startswith("Error:")


def test_symlinks_out_of_the_repo_are_not_followed(repo, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("hello outside")
    (repo / "link.txt").symlink_to(outside)
    (repo / "dirlink").symlink_to(tmp_path)
    box = ToolBox(str(repo))
    assert box.call("view", {"path": "link.txt"}).startswith("Error:")
    assert box.call("view", {"path": "dirlink/outside.txt"}).startswith("Error:")
    assert "outside" not in box.call("grep", {"pattern": "hello"})
    assert "link" not in box.call("glob", {"pattern": "*"})
    assert "link" not in box.call("view", {"path": "."})


def test_output_is_capped(repo, monkeypatch):
    (repo / "big.txt").write_text("x" * 100 + "\n")
    monkeypatch.setattr(tools, "MAX_OUTPUT_CHARS", 20)
    out = ToolBox(str(repo)).call("view", {"path": "big.txt"})
    assert out.endswith("[output truncated]") and len(out) < 60
    monkeypatch.setattr(tools, "MAX_OUTPUT_CHARS", 30_000)
    monkeypatch.setattr(tools, "MAX_RESULTS", 1)
    (repo / "b.py").write_text("hello\n")
    assert "[more results omitted]" in ToolBox(str(repo)).call(
        "grep", {"pattern": "hello"}
    )


def test_bad_regex_is_an_error_not_a_crash(repo):
    assert ToolBox(str(repo)).call("grep", {"pattern": "("}).startswith("Error:")


ANTHROPIC = "https://api.anthropic.com/v1/messages"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/g:generateContent"


@respx.mock
async def test_anthropic_tool_loop(repo):
    replies = [
        httpx.Response(
            200,
            json={
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "grep",
                        "input": {"pattern": "hello"},
                    }
                ],
            },
        ),
        httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}],
            },
        ),
    ]
    route = respx.post(ANTHROPIC).mock(side_effect=replies)
    result = await AnthropicProvider("k", "m").run("P", str(repo), 30, "plan")
    assert result.stdout == "done"
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert {t["name"] for t in first["tools"]} == {"view", "grep", "glob"}
    last = second["messages"][-1]
    assert last["role"] == "user"
    assert last["content"][0]["tool_use_id"] == "t1"
    assert "src/a.py:1:def hello" in last["content"][0]["content"]


@respx.mock
async def test_gemini_function_call_loop(repo):
    replies = [
        httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "view",
                                        "args": {"path": "README.md"},
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        ),
    ]
    route = respx.post(GEMINI).mock(side_effect=replies)
    result = await GeminiProvider("k", "g").run("P", str(repo), 30, "test")
    assert result.stdout == "ok"
    second = json.loads(route.calls[1].request.content)
    response = second["contents"][-1]["parts"][0]["functionResponse"]
    assert response["name"] == "view" and "# Title" in response["response"]["result"]
    assert "tools" in json.loads(route.calls[0].request.content)


@respx.mock
async def test_iteration_cap_stops_a_runaway_loop(repo):
    loop = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": "t", "name": "glob", "input": {"pattern": "*"}}
        ],
    }
    route = respx.post(ANTHROPIC).mock(return_value=httpx.Response(200, json=loop))
    result = await AnthropicProvider("k", "m", max_iterations=3).run("P", str(repo), 30)
    assert route.call_count == 3
    assert result.returncode == 1 and "3 tool steps" in result.stderr

    gloop = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "glob", "args": {"pattern": "*"}}}
                    ]
                }
            }
        ]
    }
    groute = respx.post(GEMINI).mock(return_value=httpx.Response(200, json=gloop))
    gresult = await GeminiProvider("k", "g", max_iterations=2).run("P", str(repo), 30)
    assert groute.call_count == 2 and "2 tool steps" in gresult.stderr


@respx.mock
async def test_summary_mode_sends_no_tools(repo):
    route = respx.post(ANTHROPIC).mock(
        return_value=httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "x"}],
            },
        )
    )
    await AnthropicProvider("k", "m").run("P", str(repo), 30, "summary")
    assert "tools" not in json.loads(route.calls[0].request.content)


@respx.mock
async def test_truncated_answer_is_an_error(repo):
    respx.post(ANTHROPIC).mock(
        return_value=httpx.Response(
            200,
            json={
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": "half"}],
            },
        )
    )
    result = await AnthropicProvider("k", "m").run("P", str(repo), 30)
    assert result.returncode == 1 and "cut its answer off" in result.stderr


def test_agent_tools_are_off_by_default(repo):
    box = ToolBox(str(repo))
    assert box.call("create", {"path": "x.txt", "content": "a"}).startswith("Error")
    assert not (repo / "x.txt").exists()
    assert [s["name"] for s in tools.tool_specs()] == ["view", "grep", "glob"]
    assert [s["name"] for s in tools.tool_specs(True)][-3:] == [
        "edit",
        "create",
        "bash",
    ]


def test_edit_and_create_write_inside_the_repo(repo):
    box = ToolBox(str(repo), agent=True)
    assert (
        box.call("create", {"path": "new/b.txt", "content": "hi"})
        == "Created new/b.txt"
    )
    assert (repo / "new" / "b.txt").read_text() == "hi"
    assert "already exists" in box.call("create", {"path": "new/b.txt", "content": "x"})
    assert (
        box.call(
            "edit", {"path": "src/a.py", "old_str": "return 1", "new_str": "return 2"}
        )
        == "Edited src/a.py"
    )
    assert "return 2" in (repo / "src" / "a.py").read_text()
    assert "exactly once" in box.call(
        "edit", {"path": "src/a.py", "old_str": "zzz", "new_str": "y"}
    )


def test_write_tools_reject_escapes_and_git_dir(repo, tmp_path):
    box = ToolBox(str(repo), agent=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("secret")
    (repo / "link").symlink_to(outside)
    assert "outside the repo" in box.call(
        "create", {"path": "../evil.txt", "content": "x"}
    )
    assert "outside the repo" in box.call(
        "create", {"path": "link/evil.txt", "content": "x"}
    )
    assert "outside the repo" in box.call(
        "edit", {"path": "link/f.txt", "old_str": "secret", "new_str": "x"}
    )
    assert "outside the repo" in box.call(
        "create", {"path": str(tmp_path / "abs.txt"), "content": "x"}
    )
    assert "cannot be changed" in box.call(
        "edit", {"path": ".git/config", "old_str": "hello", "new_str": "x"}
    )
    assert not (outside / "evil.txt").exists()
    assert (outside / "f.txt").read_text() == "secret"


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git -C . push",
        "git branch -D x",
        "git rebase main",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "rm -rf build",
        "rm -fr build",
        "rm -r -f build",
        "rm --recursive --force build",
        "sudo ls",
        "ls && git push",
        "echo hi | sudo tee x",
        "FOO=1 git push",
        "/usr/bin/git push",
        "bash -c 'git push'",
        "eval 'git push'",
        "echo $(git push)",
        "echo `git push`",
        "ls; rm -rf x",
    ],
)
def test_bash_deny_list(repo, command):
    out = ToolBox(str(repo), agent=True).call("bash", {"command": command})
    assert out.startswith("Error: Refused")


def test_bash_runs_allowed_commands_in_the_repo(repo):
    box = ToolBox(str(repo), agent=True)
    out = box.call("bash", {"command": "pwd && git --version && rm x 2>&1; echo hi"})
    assert out.startswith("exit code 0")
    assert str(repo.resolve()) in out
    assert "git version" in out
    assert "exit code 1" in box.call("bash", {"command": "exit 1"})


def test_bash_times_out_and_caps_output(repo, monkeypatch):
    box = ToolBox(str(repo), agent=True)
    monkeypatch.setattr(tools, "BASH_TIMEOUT", 0.2)
    assert "timed out" in box.call("bash", {"command": "sleep 5"})
    monkeypatch.setattr(tools, "BASH_TIMEOUT", 30)
    out = box.call("bash", {"command": "yes x | head -c 100000"})
    assert out.endswith("[output truncated]")


def _tool_turn(*calls):
    return httpx.Response(
        200,
        json={
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": f"t{i}", "name": n, "input": a}
                for i, (n, a) in enumerate(calls)
            ],
        },
    )


@respx.mock
async def test_agent_mode_offers_write_tools_and_runs_several_calls_per_turn(repo):
    route = respx.post(ANTHROPIC).mock(
        side_effect=[
            _tool_turn(
                ("create", {"path": "one.txt", "content": "1"}),
                ("edit", {"path": "README.md", "old_str": "Title", "new_str": "New"}),
                ("bash", {"command": "git --version"}),
            ),
            httpx.Response(
                200,
                json={
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "done"}],
                },
            ),
        ]
    )
    result = await AnthropicProvider("k", "m").run("P", str(repo), 30, "agent")
    assert result.returncode == 0 and result.stdout == "done"
    first = json.loads(route.calls[0].request.content)
    assert [t["name"] for t in first["tools"]] == [
        "view",
        "grep",
        "glob",
        "edit",
        "create",
        "bash",
    ]
    results = json.loads(route.calls[1].request.content)["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t0", "t1", "t2"]
    assert "git version" in results[2]["content"]
    assert (repo / "one.txt").read_text() == "1"
    assert (repo / "README.md").read_text() == "# New\n"


@respx.mock
async def test_plan_mode_stays_read_only(repo):
    route = respx.post(ANTHROPIC).mock(
        return_value=httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "x"}],
            },
        )
    )
    await AnthropicProvider("k", "m").run("P", str(repo), 30, "plan")
    names = [t["name"] for t in json.loads(route.calls[0].request.content)["tools"]]
    assert names == ["view", "grep", "glob"]


@respx.mock
async def test_agent_iteration_cap_is_configurable(repo):
    route = respx.post(ANTHROPIC).mock(
        return_value=_tool_turn(("glob", {"pattern": "*"}))
    )
    provider = AnthropicProvider("k", "m", max_iterations=2, max_agent_iterations=5)
    result = await provider.run("P", str(repo), 30, "agent")
    assert route.call_count == 5
    assert result.returncode == 1 and "5 tool steps" in result.stderr
