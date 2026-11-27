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

    reply_body = json.dumps(reply or {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
    })

    def fake(req, timeout=None):
        capture["body"] = req.data.decode()
        capture.setdefault("bodies", []).append(req.data.decode())
        capture["url"] = req.full_url
        # a non-streaming endpoint answers every request with the whole JSON,
        # including the streaming attempt (whose retry then sees the same reply)
        return _StubHTTP(reply_body.encode())

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


def test_verbose_dumps_human_readable_request_masks_key(monkeypatch):
    seen = {}
    _stub_urlopen(monkeypatch, seen)
    cfg = Config(endpoint="http://x/v1", model="m", api_key="secret-token-42")
    msgs = [{"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "leaked secret-token-42 in text " + "y" * 9000}]

    buf = io.StringIO()
    LLMClient(cfg, verbose=True, stream=buf).chat(msgs)
    out = buf.getvalue()
    # human-readable block: header line + one prefixed line per message
    assert "emerge-ai: request: model=m" in out
    assert "emerge-ai:   [1] system · 10 chars: sys prompt" in out
    assert "[capped," in out  # the 9 KB prompt field is capped with a marker
    # the JSON dump is gone: no `request payload:` line, no serialized body
    assert "request payload:" not in out and '"model": "m"' not in out
    assert "secret-token-42" not in out  # header never dumped, value masked
    assert "***" in out

    buf2 = io.StringIO()
    LLMClient(cfg, stream=buf2).chat(msgs)  # no -v: no dump lines at all
    out2 = buf2.getvalue()
    assert "request:" not in out2 and "emerge-ai:   [" not in out2
    assert "secret-token-42" not in out2


def test_verbose_dump_plain_in_pipe(monkeypatch):
    # spec «Дамп не мешает окружению прогона»: redirected stderr is plain
    seen = {}
    _stub_urlopen(monkeypatch, seen)
    buf = io.StringIO()  # non-TTY
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=buf).chat([{"role": "user", "content": "u"}])
    out = buf.getvalue()
    assert "emerge-ai:   [1] user" in out
    assert "\x1b" not in out


def test_verbose_dump_lines_have_no_json_syntax(monkeypatch):
    seen = {}
    _stub_urlopen(monkeypatch, seen, reply={
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})
    buf = io.StringIO()
    msgs = [{"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "f", "arguments": '{"a": 1}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}]
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=buf).chat(msgs)
    for line in buf.getvalue().splitlines():
        if line.startswith("emerge-ai:   "):  # dump body lines only
            assert "{" not in line and "}" not in line and '\\"' not in line, line


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

    def fake(req, timeout=None):
        # an endpoint without stream support answers the streaming attempt with
        # the plain reply; the retry without the flag must get the same reply
        if json.loads(req.data.decode()).get("stream"):
            return _StubHTTP(queue[0])
        return _StubHTTP(queue.pop(0))

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake)
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


# --- live streaming under -v (spec: llm-streaming) --------------------------

from emerge_ai import llm as llm_mod  # noqa: E402  (section-local clarity)


class _StubSSE:
    """SSE response seam (task 1.1, design D8): a context object iterated by
    byte lines like a streamed urllib reply; cut=True drops the [DONE]
    terminator to model an aborted stream."""

    def __init__(self, chunks, content_type="text/event-stream", cut=False):
        data = b"".join(chunks)
        if cut:
            data = data.rsplit(b"data: [DONE]", 1)[0]
        self._data = data
        self.headers = {"Content-Type": content_type} if content_type else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(io.BytesIO(self._data))


def _sse_bytes(*chunk_objs, keepalive=True, done=True):
    lines = [b": keep-alive\n\n"] if keepalive else []
    lines += [("data: " + json.dumps(obj) + "\n\n").encode() for obj in chunk_objs]
    if done:
        lines.append(b"data: [DONE]\n\n")
    return lines


def _delta_chunks(reasoning="", content="", tool_calls=None, finish="stop",
                  usage=None, pieces=None):
    """Split a whole reply into stream deltas (task 1.1 helper): tool-call
    arguments arrive in halves, the finish_reason rides the last choice."""
    chunks = []
    if reasoning:
        chunks.append({"choices": [{"delta": {"reasoning_content": reasoning}}]})
    if content:
        for piece in (pieces or [content]):
            chunks.append({"choices": [{"delta": {"content": piece}}]})
    for i, call in enumerate(tool_calls or []):
        args = call["function"].get("arguments") or ""
        mid = len(args) // 2
        chunks.append({"choices": [{"delta": {"tool_calls": [
            {"index": i, "id": call["id"], "type": "function",
             "function": {"name": call["function"]["name"],
                          "arguments": args[:mid]}}]}}]})
        chunks.append({"choices": [{"delta": {"tool_calls": [
            {"index": i, "function": {"arguments": args[mid:]}}]}}]})
    chunks.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    if usage:
        chunks.append({"choices": [], "usage": usage})
    return chunks


def _whole_reply(content="", reasoning="", tool_calls=None, finish="stop"):
    msg = {"content": content, "reasoning_content": reasoning}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish}]}


def _stub_sse_stream(monkeypatch, calls, chunks_by_stream, plain_reply=None):
    """urlopen seam: streaming attempts get SSE bytes from chunks_by_stream
    (popped per stream request); non-stream requests get plain_reply."""

    def fake(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        if body.get("stream"):
            return chunks_by_stream.pop(0)
        return _StubHTTP(json.dumps(plain_reply or {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        }).encode())

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake)


# -- SSE iterator (task 1.3) --


def test_sse_iterator_skips_keepalive_and_garbage():
    stats = {"bad": 0, "done": False, "chunks": 0}
    chunks = _sse_bytes(*_delta_chunks(content="hi"))
    chunks.insert(2, b"data: {not json at all}\n\n")
    chunks.insert(3, b"event: message\n\n")
    got = list(llm_mod._iter_sse(_StubSSE(chunks), stats))
    assert stats["bad"] == 1 and stats["done"] is True
    assert stats["chunks"] == len(got) >= 2  # garbage skipped, rest delivered


def test_sse_iterator_stream_without_tool_calls_and_no_keepalive():
    stats = {"bad": 0, "done": False, "chunks": 0}
    chunks = _sse_bytes({"choices": [{"delta": {"content": "x"}}]},
                        keepalive=False)
    got = list(llm_mod._iter_sse(_StubSSE(chunks), stats))
    assert [c["choices"][0]["delta"]["content"] for c in got] == ["x"]
    assert stats == {"bad": 0, "done": True, "chunks": 1}


# -- accumulator equivalence (task 1.4) --


def test_accumulated_stream_equals_parsed_whole():
    one = {"id": "c1", "type": "function",
           "function": {"name": "f", "arguments": '{"a": 1}'}}
    two = {"id": "c2", "type": "function",
           "function": {"name": "g", "arguments": '{"b": "text", "c": [1, 2]}'}}
    broken = {"id": "c3", "type": "function",
              "function": {"name": "h", "arguments": '{"a": '}}
    cases = [
        dict(content="hello world", reasoning="think"),
        dict(reasoning="pure thinking"),
        dict(content="calling", tool_calls=[one], finish="tool_calls"),
        dict(tool_calls=[one, two], finish="tool_calls"),
        dict(content="half an idea", finish="length"),
        dict(tool_calls=[broken], finish="tool_calls"),  # _raw fallback too
    ]
    for case in cases:
        whole = LLMClient._parse(_whole_reply(**case))
        streamed, _usage = llm_mod._accumulate(_delta_chunks(**case))
        assert streamed == whole, case
    # finish_reason: the last non-empty one wins
    streamed, _ = llm_mod._accumulate(
        [{"choices": [{"delta": {"content": "a"}, "finish_reason": None}]},
         {"choices": [{"delta": {}, "finish_reason": "stop"}]}])
    assert streamed.finish_reason == "stop"


def test_accumulator_collects_usage_outside_response():
    streamed, usage = llm_mod._accumulate(
        _delta_chunks(content="x", usage={"prompt_tokens": 10, "completion_tokens": 5}))
    assert usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert not hasattr(streamed, "usage")


# -- request body (task 2.1) --


def test_stream_flag_sent_only_under_verbose(monkeypatch):
    seen = {}
    _stub_urlopen(monkeypatch, seen)
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=io.StringIO()).chat([{"role": "user", "content": "u"}])
    bodies = [json.loads(b) for b in seen["bodies"]]
    assert bodies[0]["stream"] is True
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert all("stream" not in b for b in bodies[1:])  # the retry, payload as before

    quiet = {}
    _stub_urlopen(monkeypatch, quiet)
    LLMClient(Config(endpoint="http://x/v1"),
              stream=io.StringIO()).chat([{"role": "user", "content": "u"}])
    assert len(quiet["bodies"]) == 1
    assert "stream" not in json.loads(quiet["body"])


# -- fallback (tasks 2.2-2.4) --


def test_wrong_content_type_retries_once_without_stream(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE([], content_type="application/json")])
    buf = io.StringIO()
    resp = LLMClient(Config(endpoint="http://x/v1"), verbose=True,
                     stream=buf).chat([{"role": "user", "content": "u"}])
    assert resp.content == "hi" and not resp.displayed  # run continued
    assert len(calls) == 2 and "stream" not in calls[1]
    err = buf.getvalue()
    assert err.count("event stream") == 1  # one -v warning only


def test_stream_supported_refusal_is_remembered(monkeypatch):
    # tool loop of three calls against a non-streaming endpoint: the refusal
    # costs one retry total, the later calls are single requests (task 2.3)
    one = {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    replies = [
        _whole_reply(content="", tool_calls=[one], finish="tool_calls"),
        _whole_reply(content="", reasoning="R2", tool_calls=[dict(one, id="c2")],
                     finish="tool_calls"),
        _whole_reply(content="done"),
    ]
    calls = []

    def fake(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        if body.get("stream"):
            return _StubSSE([], content_type="application/json")
        return _StubHTTP(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake)
    buf = io.StringIO()
    client = LLMClient(Config(endpoint="http://x/v1"), verbose=True, stream=buf)
    final = run_tool_loop(client, [{"role": "user", "content": "u"}],
                          [{"type": "function"}], lambda name, args: {"ok": True},
                          render_to=buf)
    assert final.content == "done"
    assert len(calls) == 4  # 1 refused + 3 plain
    assert sum(1 for c in calls if c.get("stream")) == 1
    assert buf.getvalue().count("event stream") == 1


def test_abort_after_first_show_is_llm_error_without_retry(monkeypatch):
    calls = []
    chunks = _sse_bytes(*_delta_chunks(content="partial answer"))
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(chunks, cut=True)],
                     plain_reply=_whole_reply(content="NEVER"))
    buf = io.StringIO()
    client = LLMClient(Config(endpoint="http://x/v1"), verbose=True, stream=buf)
    with pytest.raises(LLMError) as excinfo:
        client.chat([{"role": "user", "content": "u"}])
    assert "stream ended before [DONE]" in str(excinfo.value)
    assert len(calls) == 1  # no silent duplicate on screen (spec scenario)
    out = buf.getvalue()
    assert "partial answer" in out and "NEVER" not in out
    # the half line is terminated before anything else can be written
    assert "partial answer\n" in out


def test_abort_before_any_show_falls_back(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls, [_StubSSE([], cut=True)],
                     plain_reply=_whole_reply(content="late reply"))
    buf = io.StringIO()
    resp = LLMClient(Config(endpoint="http://x/v1"), verbose=True,
                     stream=buf).chat([{"role": "user", "content": "u"}])
    assert resp.content == "late reply" and len(calls) == 2


# -- live presentation (tasks 3.1-3.3) --


def test_stream_prints_reasoning_then_content_then_duration(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(_sse_bytes(*_delta_chunks(reasoning="think ",
                                                         content="answer")))])
    buf = io.StringIO()
    resp = LLMClient(Config(endpoint="http://x/v1"), verbose=True,
                     stream=buf).chat([{"role": "user", "content": "u"}])
    out = buf.getvalue()
    assert out.index("think") < out.index("answer") < out.index("LLM answered")
    assert resp.displayed and resp.reasoning == "think " and resp.content == "answer"
    # duration line exactly once, old substrings intact
    assert out.count("LLM answered in ") == 1 and "(finish=stop)" in out


def test_stream_reasoning_colored_and_plain_in_pipe(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(_sse_bytes(*_delta_chunks(reasoning="deep thought")))])
    tty = TTY()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=tty).chat([{"role": "user", "content": "u"}])
    assert "\x1b[2mdeep thought\x1b[0m" in tty.getvalue()

    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(_sse_bytes(*_delta_chunks(reasoning="deep thought")))])
    pipe = io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=pipe).chat([{"role": "user", "content": "u"}])
    out = pipe.getvalue()
    assert out.count("deep thought") == 1 and "\x1b" not in out
    assert "[reasoning] deep thought" in out  # the -v marker survives streaming


def test_stream_question_line_colored_whole_across_chunks(monkeypatch):
    calls = []
    chunks = _sse_bytes(*_delta_chunks(
        content="hello\nQUESTION: proceed?\nbye",
        pieces=["hello\nQUEST", "ION: proceed?", "\nbye"]))
    _stub_sse_stream(monkeypatch, calls, [chunks and _StubSSE(chunks)])
    tty = TTY()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=tty).chat([{"role": "user", "content": "u"}])
    out = tty.getvalue()
    assert "\x1b[33mQUESTION: proceed?\x1b[0m" in out  # whole line, one color
    assert "\x1b[36mhello\x1b[0m" in out and "\x1b[36mbye\x1b[0m" in out
    assert "QUEST\x1b" not in out and "\x1b[33mION" not in out  # no torn paint


def test_stream_partial_line_not_glued_to_next_activity(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(_sse_bytes(*_delta_chunks(content="no trailing newline")))])
    buf = io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=buf).chat([{"role": "user", "content": "u"}])
    out = buf.getvalue()
    assert "no trailing newline\nemerge-ai: LLM answered" in out


def test_stream_duration_line_appends_usage_tokens(monkeypatch):
    calls = []
    _stub_sse_stream(monkeypatch, calls,
                     [_StubSSE(_sse_bytes(*_delta_chunks(
                         content="x", usage={"prompt_tokens": 12,
                                             "completion_tokens": 34})))])
    buf = io.StringIO()
    LLMClient(Config(endpoint="http://x/v1"), verbose=True,
              stream=buf).chat([{"role": "user", "content": "u"}])
    out = buf.getvalue()
    assert out.count("LLM answered in ") == 1
    assert "(finish=stop)" in out and "[tokens 12+34]" in out


# -- exactly-once through the tool loop (task 3.4) --


def test_stream_tool_loop_shows_every_turn_exactly_once(monkeypatch):
    one = {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    calls = []
    streams = [
        _StubSSE(_sse_bytes(*_delta_chunks(reasoning="R1", content="",
                                           tool_calls=[one], finish="tool_calls"))),
        _StubSSE(_sse_bytes(*_delta_chunks(reasoning="R2", content="done"))),
    ]

    def fake(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        return streams.pop(0)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake)
    buf = io.StringIO()
    client = LLMClient(Config(endpoint="http://x/v1"), verbose=True, stream=buf)
    final = run_tool_loop(client, [{"role": "user", "content": "u"}],
                          [{"type": "function"}], lambda name, args: {"ok": True},
                          render_to=buf)
    assert final.content == "done"
    out = buf.getvalue()
    assert out.count("R1") == 1 and out.count("R2") == 1 and out.count("done") == 1
