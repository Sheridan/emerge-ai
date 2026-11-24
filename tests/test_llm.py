import io
import os

import pytest

from emerge_ai.config import Config
from emerge_ai.llm import (
    LimitExhausted,
    LLMClient,
    LLMError,
    Response,
    ToolCall,
    run_tool_loop,
)

ENDPOINT = os.environ.get("EMERGE_AI_TEST_ENDPOINT", "http://127.0.0.1:8080/v1")
MODEL = os.environ.get(
    "EMERGE_AI_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"
)


def _live_client(**client_kw) -> LLMClient:
    return LLMClient(Config(endpoint=ENDPOINT, model=MODEL), **client_kw)


def test_parse_tool_calls_payload():
    data = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "reasoning_content": "think",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"a": 1}'},
                        }
                    ],
                },
            }
        ]
    }
    resp = LLMClient._parse(data)
    assert resp.finish_reason == "tool_calls"
    assert resp.reasoning == "think"
    assert resp.tool_calls[0].name == "f" and resp.tool_calls[0].arguments == {"a": 1}


def test_render_reasoning_only_when_enabled():
    resp = Response(content="answer", reasoning="because")
    buf_on, buf_off = io.StringIO(), io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), show_reasoning=True).render(resp, stream=buf_on)
    LLMClient(Config(endpoint="http://x/v1")).render(resp, stream=buf_off)
    assert "[reasoning] because" in buf_on.getvalue()
    assert "answer" in buf_on.getvalue()
    assert "[reasoning]" not in buf_off.getvalue()
    assert "answer" in buf_off.getvalue()


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_render_tty_uses_palette_colors():
    resp = Response(content="hello\nQUESTION: init?", reasoning="think")
    buf = TTY()
    LLMClient(Config(endpoint="http://x/v1"), show_reasoning=True).render(resp, stream=buf)
    out = buf.getvalue()
    assert "\x1b[2m[reasoning] think\x1b[0m" in out
    assert "\x1b[36mhello\x1b[0m" in out
    assert "\x1b[33mQUESTION: init?\x1b[0m" in out


def test_render_custom_and_off_palette_never_escape_on_pipe():
    resp = Response(content="hello")
    cfg = Config(endpoint="http://x/v1", llm_colors={"content": "magenta", "reasoning": "off"})
    buf = TTY()
    LLMClient(cfg).render(resp, stream=buf)
    assert buf.getvalue() == "\x1b[35mhello\x1b[0m\n"
    buf2 = io.StringIO()
    LLMClient(cfg).render(resp, stream=buf2)
    assert buf2.getvalue() == "hello\n"


def test_no_endpoint_raises():
    with pytest.raises(LLMError):
        LLMClient(Config())


# --- LimitExhausted: distinguishable limit signal (handle-agent-limit-exhaustion / M13) ---


class ScriptedLoopClient:
    """Minimal fake client for run_tool_loop: replays canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.2):
        self.calls += 1
        return self.responses.pop(0)

    def render(self, resp, stream=None):
        pass


def test_limit_exhausted_is_a_distinguishable_llm_error():
    assert issubclass(LimitExhausted, LLMError)
    exc = LimitExhausted("tokens", partial=Response(content="half"), messages=[])
    assert exc.reason == "tokens"
    assert exc.partial.content == "half"
    assert "tokens" in str(exc)


def test_truncated_answer_raises_limit_exhausted_not_final_answer():
    # spec «Ответ обрезан на лимите»: never published as a finished proposal
    client = ScriptedLoopClient([Response(content="half an idea", finish_reason="length")])
    msgs = [{"role": "user", "content": "analyze"}]
    with pytest.raises(LimitExhausted) as ei:
        run_tool_loop(client, msgs, [], lambda name, args: {})
    assert ei.value.reason == "tokens"
    assert ei.value.partial.content == "half an idea"
    # the message history travels with the signal — resumption starts from it
    assert ei.value.messages[0]["content"] == "analyze"


def test_truncated_tool_calls_are_never_executed():
    # a generation cut at the limit can carry half-written arguments (design risk D3)
    executed = []

    def dispatch(name, args):
        executed.append(name)
        return {}

    client = ScriptedLoopClient([
        Response(content="", finish_reason="length",
                 tool_calls=[ToolCall(id="c1", name="run_command", arguments={"cmd": "rm"})])
    ])
    with pytest.raises(LimitExhausted) as ei:
        run_tool_loop(client, [{"role": "user", "content": "go"}], [], dispatch)
    assert ei.value.reason == "tokens"
    assert executed == []


def test_round_budget_raises_limit_exhausted_with_history():
    class AlwaysTool:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None, temperature=0.2):
            self.n += 1
            return Response(content="", tool_calls=[
                ToolCall(id=f"c{self.n}", name="t", arguments={})])

        def render(self, resp, stream=None):
            pass

    seen = []

    def dispatch(name, args):
        seen.append(name)
        return {"ok": True}

    with pytest.raises(LimitExhausted) as ei:
        run_tool_loop(AlwaysTool(), [{"role": "user", "content": "go"}], [], dispatch,
                      max_rounds=3)
    assert ei.value.reason == "rounds"
    assert seen == ["t", "t", "t"]
    assert any(m["role"] == "tool" for m in ei.value.messages)


# ---------------- live strata replay (design D13: all LLM tests hit strata) ----


@pytest.mark.integration
def test_live_tool_call_loop_executes():
    client = _live_client()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_pkg_info",
                "description": "Return installed version info for a package",
                "parameters": {
                    "type": "object",
                    "properties": {"category": {"type": "string"}},
                    "required": ["category"],
                },
            },
        }
    ]
    executed = []

    def dispatch(name, args):
        executed.append((name, args))
        return {"name": name, "version": "1.3.2", "slot": "0/1.3.2"}

    final = run_tool_loop(
        client,
        [
            {
                "role": "user",
                "content": (
                    "You MUST call the get_pkg_info tool with category 'sys-libs/zlib' "
                    "and then tell me the version from the tool result."
                ),
            }
        ],
        tools,
        dispatch,
    )
    assert executed and executed[0][0] == "get_pkg_info"
    assert "1.3.2" in final.content


@pytest.mark.integration
def test_live_reasoning_visibility():
    on, off = _live_client(show_reasoning=True), _live_client()
    prompt = (
        "A package queue has 3 tiers with 2, 5 and 1 packages. How many total? "
        "Show the number."
    )
    buf_on, buf_off = io.StringIO(), io.StringIO()
    r_on = on.chat([{"role": "user", "content": prompt}])
    r_off = off.chat([{"role": "user", "content": prompt}])
    on.render(r_on, stream=buf_on)
    off.render(r_off, stream=buf_off)
    if r_on.reasoning:
        assert "[reasoning]" in buf_on.getvalue()
    assert "[reasoning]" not in buf_off.getvalue()
    assert "8" in r_on.content + r_off.content
