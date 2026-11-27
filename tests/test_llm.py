import io
import json
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


def test_chat_prints_reasoning_only_when_verbose(monkeypatch):
    # spec: config-prompts — the single print site is chat() itself: every
    # call shows thinking under -v, direct chats included; quiet without it
    seen = {}
    reply = {"choices": [{"message": {"content": "answer", "reasoning_content": "because"},
                          "finish_reason": "stop"}]}
    _stub_urlopen(monkeypatch, seen, reply=reply)
    buf_on, buf_off = io.StringIO(), io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=buf_on).chat([{"role": "user", "content": "u"}])
    _stub_urlopen(monkeypatch, seen, reply=reply)
    LLMClient(Config(endpoint="http://x/v1"),
              stream=buf_off).chat([{"role": "user", "content": "u"}])
    assert "[reasoning] because" in buf_on.getvalue()
    assert "[reasoning]" not in buf_off.getvalue()
    assert "answer" in buf_off.getvalue()  # quiet is reasoning-only, never content


def test_render_is_content_only():
    # render() lost its reasoning branch (change fix-verbose-thinking-output):
    # the tool loop must not print what chat() already printed
    resp = Response(content="answer", reasoning="because")
    buf = io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True).render(resp, stream=buf)
    assert "[reasoning]" not in buf.getvalue()
    assert "answer" in buf.getvalue()


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_chat_reasoning_uses_palette_and_stays_plain_in_pipe(monkeypatch):
    reply = {"choices": [{"message": {"content": "", "reasoning_content": "think"},
                          "finish_reason": "stop"}]}
    seen = {}
    _stub_urlopen(monkeypatch, seen, reply=reply)
    tty = TTY()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=tty).chat([{"role": "user", "content": "u"}])
    assert "\x1b[2m[reasoning] think\x1b[0m" in tty.getvalue()  # dim, fainter than content

    pipe = io.StringIO()
    _stub_urlopen(monkeypatch, seen, reply=reply)
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=pipe).chat([{"role": "user", "content": "u"}])
    assert "\x1b" not in pipe.getvalue() and "[reasoning] think" in pipe.getvalue()

    off = TTY()
    _stub_urlopen(monkeypatch, seen, reply=reply)
    cfg = Config(endpoint="http://x/v1", llm_colors={"reasoning": "off"})
    LLMClient(cfg, verbose=True, stream=off).chat([{"role": "user", "content": "u"}])
    assert "[reasoning] think" in off.getvalue() and "\x1b" not in off.getvalue()


def test_render_tty_uses_palette_colors():
    resp = Response(content="hello\nQUESTION: init?", reasoning="think")
    buf = TTY()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True).render(resp, stream=buf)
    out = buf.getvalue()
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


# --- progress logging: chat-level visibility (spec: progress-logging) ------


class _StubHTTP(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_urlopen(monkeypatch, capture, reply=None):
    from emerge_ai import llm as llm_mod

    def fake(req, timeout=None):
        capture["body"] = req.data.decode()
        capture["url"] = req.full_url
        return _StubHTTP(json.dumps(reply or {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        }).encode())

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake)


def test_chat_announces_request_then_answer(monkeypatch):
    seen = {}
    _stub_urlopen(monkeypatch, seen)
    buf = io.StringIO()
    client = LLMClient(Config(endpoint="http://x/v1", model="m1"), stream=buf)
    client.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                tools=[{"type": "function"}])
    out = buf.getvalue()
    assert "emerge-ai: sending request to LLM (model=m1, 2 messages, tools=1)" in out
    assert "emerge-ai: LLM answered in " in out and "(finish=stop)" in out
    # order: announcement precedes the answer line
    assert out.index("sending request") < out.index("LLM answered")


def test_announcements_default_to_stderr(monkeypatch):
    import sys

    seen = {}
    _stub_urlopen(monkeypatch, seen)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    LLMClient(Config(endpoint="http://x/v1")).chat([{"role": "user", "content": "u"}])
    assert "emerge-ai: sending request to LLM" in buf.getvalue()


def test_verbose_dumps_request_payload_masks_key_and_caps(monkeypatch):
    seen = {}
    _stub_urlopen(monkeypatch, seen)
    cfg = Config(endpoint="http://x/v1", model="m", api_key="secret-token-42")
    msgs = [{"role": "user", "content": "leaked secret-token-42 in text " + "y" * 9000}]

    buf = io.StringIO()
    LLMClient(cfg, verbose=True, stream=buf).chat(msgs)
    out = buf.getvalue()
    assert "request payload:" in out and '"model": "m"' in out
    assert "secret-token-42" not in out  # header never dumped, value masked
    assert "***" in out
    assert "[capped," in out  # the 9 KB prompt dump is capped with a marker

    buf2 = io.StringIO()
    LLMClient(cfg, stream=buf2).chat(msgs)  # no -v: no payload, no leak either
    out2 = buf2.getvalue()
    assert "request payload" not in out2 and "secret-token-42" not in out2


# --- reasoning exactly-once through the tool loop (change fix-verbose-thinking) ---


def test_tool_loop_prints_each_reasoning_exactly_once(monkeypatch):
    from emerge_ai import llm as llm_mod

    def reply(reasoning, content="", with_tool_call=False):
        msg = {"content": content, "reasoning_content": reasoning}
        finish = "stop"
        if with_tool_call:
            msg["tool_calls"] = [{"id": "c1", "type": "function",
                                  "function": {"name": "f", "arguments": "{}"}}]
            finish = "tool_calls"
        return json.dumps({"choices": [{"message": msg, "finish_reason": finish}]}).encode()

    queue = [reply("R1", with_tool_call=True), reply("R2", content="done")]
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _StubHTTP(queue.pop(0)))
    buf = io.StringIO()
    client = LLMClient(Config(endpoint="http://x/v1"), verbose=True, stream=buf)
    final = run_tool_loop(client, [{"role": "user", "content": "u"}],
                          [{"type": "function"}], lambda name, args: {"ok": True},
                          render_to=buf)
    assert final.content == "done"
    out = buf.getvalue()
    # chat printed each turn's reasoning; render (content-only) did not repeat it
    assert out.count("[reasoning] R1") == 1 and out.count("[reasoning] R2") == 1
    assert "done" in out


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
    prompt = (
        "A package queue has 3 tiers with 2, 5 and 1 packages. How many total? "
        "Show the number."
    )
    # chat() is the print seam now: verbose client prints [reasoning] to its
    # stream as soon as the reply is parsed
    buf_on, buf_off = io.StringIO(), io.StringIO()
    on, off = _live_client(verbose=True, stream=buf_on), _live_client(stream=buf_off)
    r_on = on.chat([{"role": "user", "content": prompt}])
    r_off = off.chat([{"role": "user", "content": prompt}])
    if r_on.reasoning:
        assert "[reasoning]" in buf_on.getvalue()
    assert "[reasoning]" not in buf_off.getvalue()
    assert "8" in r_on.content + r_off.content
