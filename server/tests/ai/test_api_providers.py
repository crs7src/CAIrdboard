import httpx
import pytest
import respx

from app.ai import make_provider, verify_key
from app.ai.anthropic import AnthropicProvider
from app.ai.errors import ProviderError
from app.ai.gemini import GeminiProvider
from app.core.config import Settings
from app.stages.planner import CommandTimeout

KEY = "super-secret-key-123"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gem-1:generateContent"
)


def anthropic():
    return AnthropicProvider(KEY, "claude-x")


def gemini():
    return GeminiProvider(KEY, "gem-1")


def anthropic_ok(text="the plan"):
    return httpx.Response(
        200,
        json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"},
    )


def gemini_ok(text="the plan"):
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


@respx.mock
async def test_anthropic_request_shape_and_text():
    route = respx.post(ANTHROPIC_URL).mock(return_value=anthropic_ok("A\nB"))
    result = await anthropic().run("PROMPT", "/repo", 30)
    assert (result.returncode, result.stdout) == (0, "A\nB")
    request = route.calls[0].request
    assert request.headers["x-api-key"] == KEY
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = __import__("json").loads(request.content)
    assert body["model"] == "claude-x"
    assert body["max_tokens"] > 0
    assert body["messages"] == [{"role": "user", "content": "PROMPT"}]


@respx.mock
async def test_gemini_request_shape_and_text():
    route = respx.post(GEMINI_URL).mock(return_value=gemini_ok("hello"))
    result = await gemini().run("PROMPT", "/repo", 30)
    assert (result.returncode, result.stdout) == (0, "hello")
    request = route.calls[0].request
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    body = __import__("json").loads(request.content)
    assert body["contents"][0]["parts"] == [{"text": "PROMPT"}]


CASES = [
    (401, "did not accept the API key"),
    (403, "did not accept the API key"),
    (429, "rate limit"),
    (500, "problems (HTTP 500)"),
    (503, "problems (HTTP 503)"),
]


@pytest.mark.parametrize(("status", "message"), CASES)
@respx.mock
async def test_http_errors_become_failed_results_without_the_key(status, message):
    body = {"error": {"message": f"bad {KEY} thing"}}
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(status, json=body))
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(status, json=body))
    for provider in (anthropic(), gemini()):
        result = await provider.run("p", "/repo", 30)
        assert result.returncode == 1 and result.stdout == ""
        assert message in result.stderr
        assert KEY not in result.stderr


@respx.mock
async def test_timeout_raises_command_timeout():
    respx.post(ANTHROPIC_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.post(GEMINI_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    for provider in (anthropic(), gemini()):
        with pytest.raises(CommandTimeout):
            await provider.run("p", "/repo", 30)


@respx.mock
async def test_connection_error_is_a_failed_result():
    respx.post(ANTHROPIC_URL).mock(side_effect=httpx.ConnectError(KEY))
    result = await anthropic().run("p", "/repo", 30)
    assert result.returncode == 1 and "Could not reach" in result.stderr
    assert KEY not in result.stderr


@respx.mock
async def test_empty_output_is_a_failed_result():
    respx.post(ANTHROPIC_URL).mock(return_value=anthropic_ok("  "))
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200, json={"promptFeedback": {"blockReason": "SAFETY"}}
        )
    )
    a = await anthropic().run("p", "/repo", 30)
    g = await gemini().run("p", "/repo", 30)
    assert a.returncode == 1 and "no text" in a.stderr
    assert g.returncode == 1 and "SAFETY" in g.stderr


@respx.mock
async def test_verify_uses_free_calls_and_reports_bad_keys():
    models = respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await verify_key("anthropic", KEY, "m")
    assert models.calls[0].request.headers["x-api-key"] == KEY
    respx.get("https://generativelanguage.googleapis.com/v1beta/models/gem-1").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "API key not valid"}}
        )
    )
    with pytest.raises(ProviderError) as info:
        await verify_key("gemini", KEY, "gem-1")
    assert KEY not in str(info.value)


def test_make_provider_needs_a_key_and_uses_the_model():
    settings = Settings(anthropic_api_key=KEY, _env_file=None)
    provider = make_provider("anthropic", settings, None, "claude-y")
    assert isinstance(provider, AnthropicProvider) and provider.model == "claude-y"
    with pytest.raises(Exception, match="no API key"):
        make_provider("gemini", settings, None)
    assert make_provider("anthropic", settings, None).model


def gemini_call(name, args):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": name, "args": args}}],
                    }
                }
            ]
        },
    )


@respx.mock
async def test_gemini_agent_edits_runs_bash_and_answers(tmp_path):
    (tmp_path / "a.txt").write_text("old")
    route = respx.post(GEMINI_URL).mock(
        side_effect=[
            gemini_call("edit", {"path": "a.txt", "old_str": "old", "new_str": "new"}),
            gemini_call("bash", {"command": "echo hi"}),
            gemini_ok("done"),
        ]
    )
    result = await gemini().run("p", str(tmp_path), 30, mode="agent")
    assert (result.returncode, result.stdout) == (0, "done")
    assert (tmp_path / "a.txt").read_text() == "new"
    first = __import__("json").loads(route.calls[0].request.content)
    names = [d["name"] for d in first["tools"][0]["functionDeclarations"]]
    assert {"edit", "create", "bash"} <= set(names)
    last = __import__("json").loads(route.calls[2].request.content)
    reply = last["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "hi" in reply


@respx.mock
async def test_gemini_agent_denied_bash_goes_back_to_model(tmp_path):
    route = respx.post(GEMINI_URL).mock(
        side_effect=[gemini_call("bash", {"command": "git push"}), gemini_ok("ok")]
    )
    result = await gemini().run("p", str(tmp_path), 30, mode="agent")
    assert result.returncode == 0
    last = __import__("json").loads(route.calls[1].request.content)
    reply = last["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert (
        "refus" in reply.lower()
        or "not allowed" in reply.lower()
        or "denied" in reply.lower()
    )


@respx.mock
async def test_gemini_read_only_modes_get_no_agent_tools(tmp_path):
    route = respx.post(GEMINI_URL).mock(return_value=gemini_ok())
    await gemini().run("p", str(tmp_path), 30)
    body = __import__("json").loads(route.calls[0].request.content)
    names = [d["name"] for d in body["tools"][0]["functionDeclarations"]]
    assert names == ["view", "grep", "glob"]


@respx.mock
async def test_gemini_agent_iteration_cap_and_max_tokens(tmp_path):
    respx.post(GEMINI_URL).mock(return_value=gemini_call("glob", {"pattern": "*"}))
    capped = GeminiProvider(KEY, "gem-1", max_agent_iterations=2)
    result = await capped.run("p", str(tmp_path), 30, mode="agent")
    assert result.returncode == 1 and "2 tool steps" in result.stderr
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "part"}]},
                    }
                ]
            },
        )
    )
    result = await gemini().run("p", str(tmp_path), 30, mode="agent")
    assert result.returncode == 1 and "too long" in result.stderr
    assert KEY not in result.stderr
