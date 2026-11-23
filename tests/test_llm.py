import io
import os

import pytest

from emerge_ai.config import Config
from emerge_ai.llm import LLMClient, LLMError, Response, run_tool_loop

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


def test_no_endpoint_raises():
    with pytest.raises(LLMError):
        LLMClient(Config())


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
