import io
import json
import re

import pytest

from emerge_ai import ui


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_color_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)


def test_supports_color_matrix(monkeypatch):
    assert ui.supports_color(TTY()) is True
    assert ui.supports_color(io.StringIO()) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.supports_color(TTY()) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert ui.supports_color(TTY()) is False
    monkeypatch.setenv("TERM", "xterm-256color")
    assert ui.supports_color(TTY()) is True


def test_supports_color_is_per_call(monkeypatch):
    tty = TTY()
    assert ui.supports_color(tty) is True
    monkeypatch.setenv("NO_COLOR", "")  # empty value: unset per NO_COLOR convention
    assert ui.supports_color(tty) is True
    monkeypatch.setenv("NO_COLOR", "0")
    assert ui.supports_color(tty) is False


def test_paint_wraps_only_on_tty():
    assert ui.paint(TTY(), "31", "boom") == "\x1b[31mboom\x1b[0m"
    assert ui.paint(io.StringIO(), "31", "boom") == "boom"
    assert ui.paint(TTY(), "", "boom") == "boom"
    assert ui.paint(TTY(), "31", "") == ""


def test_paint_composite_sgr():
    assert ui.paint(TTY(), "1;33", "Proceed?") == "\x1b[1;33mProceed?\x1b[0m"


def test_strip_ansi_removes_csi_and_osc():
    raw = "\x1b[1;32m[ebuild   N    ]\x1b[0m app-misc/foo \x1b]0;title\x07 done\x1b[0m\n"
    assert ui.strip_ansi(raw) == "[ebuild   N    ] app-misc/foo  done\n"


def test_strip_ansi_keeps_plain_text():
    assert ui.strip_ansi("no escapes here") == "no escapes here"


def test_color_whitelist_maps_names():
    assert ui.color_sgr("red") == "31"
    assert ui.color_sgr("bright-cyan") == "96"
    assert ui.color_sgr("dim") == "2"
    assert ui.color_sgr("bold") == "1"
    assert ui.color_sgr("off") == ""
    assert ui.color_sgr(None) == ""
    assert ui.color_sgr("\x1b[38;5;9m") == ""  # raw escape strings never map


def test_resolve_palette_valid_partial_and_off():
    pal = ui.resolve_palette({"content": "magenta", "question": "off"})
    assert pal == {"content": "magenta", "reasoning": "dim", "question": "off"}


def test_resolve_palette_invalid_warns_and_defaults():
    warns = []
    pal = ui.resolve_palette({"content": "hot-pink", "reasoning": None}, warn=warns.append)
    assert pal["content"] == "cyan"
    assert pal["reasoning"] is None  # explicit null = off, not invalid
    assert len(warns) == 1 and "hot-pink" in warns[0] and "content" in warns[0]


def test_resolve_palette_non_dict_warns_all_defaults():
    warns = []
    pal = ui.resolve_palette("cyan", warn=warns.append)
    assert pal == ui.DEFAULT_LLM_COLORS
    assert warns and "JSON object" in warns[0]


def test_resolve_palette_none_is_quiet_defaults():
    warns = []
    assert ui.resolve_palette(None, warn=warns.append) == ui.DEFAULT_LLM_COLORS
    assert warns == []


def test_message_helpers_color_on_tty():
    assert ui.err("bad", stream=TTY()) == "\x1b[31memerge-ai: bad\x1b[0m"
    assert ui.warn("meh", stream=TTY()) == "\x1b[33memerge-ai: meh\x1b[0m"
    assert ui.ok("fine", stream=TTY()) == "\x1b[32memerge-ai: fine\x1b[0m"
    assert ui.info("note", stream=TTY()) == "emerge-ai: note"
    assert ui.prompt("Proceed? [y/N] ", stream=TTY()) == "\x1b[1;33mProceed? [y/N] \x1b[0m"


def test_message_helpers_plain_on_pipe():
    pipe = io.StringIO()
    assert ui.err("bad", stream=pipe) == "emerge-ai: bad"
    assert ui.warn("meh", stream=pipe) == "emerge-ai: meh"
    assert ui.ok("fine", stream=pipe) == "emerge-ai: fine"
    assert ui.prompt("Proceed? ", stream=pipe) == "Proceed? "


def test_activity_is_plain_info_style_even_on_tty(monkeypatch):
    # spec: progress-logging — activity lines follow console-output info style:
    # no color accent, identical text on TTY, pipe, NO_COLOR
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert ui.activity("running: emerge -p x", stream=TTY()) == "emerge-ai: running: emerge -p x"
    assert "\x1b" not in ui.activity("m", stream=TTY())
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.activity("m", stream=TTY()) == "emerge-ai: m"


def test_clip_caps_with_marker():
    assert ui.clip("short", 200) == "short"
    out = ui.clip("x" * 260, 200)
    assert out.startswith("x" * 200)
    assert out.endswith("[capped, 260 chars total]")


def test_helpers_default_streams_resolved_at_call_time(monkeypatch):
    tty = TTY()
    monkeypatch.setattr(ui.sys, "stderr", tty)
    monkeypatch.setattr(ui.sys, "stdout", tty)
    assert ui.err("bad").startswith("\x1b[31m")
    assert ui.prompt("Proceed? ").startswith("\x1b[1;33m")


def test_paint_llm_block_question_marker_gets_question_color():
    tty = TTY()
    ui.paint_llm_block("relink the lib\nQUESTION: which init?", ui.DEFAULT_LLM_COLORS, tty)
    out = tty.getvalue()
    assert "\x1b[36mrelink the lib\x1b[0m" in out
    assert "\x1b[33mQUESTION: which init?\x1b[0m" in out


def test_paint_llm_block_off_and_invalid_palette():
    tty = TTY()
    ui.paint_llm_block("a\nQUESTION: b?", {"content": "off", "question": "off"}, tty)
    assert tty.getvalue() == "a\nQUESTION: b?\n"
    tty2 = TTY()
    ui.paint_llm_block("a", {"content": "hot-pink"}, tty2)
    assert tty2.getvalue() == "\x1b[36ma\x1b[0m\n"  # invalid name -> default, never raw input


def test_paint_llm_block_plain_stream_never_escapes():
    pipe = io.StringIO()
    ui.paint_llm_block("x\nQUESTION: y?", ui.DEFAULT_LLM_COLORS, pipe)
    assert pipe.getvalue() == "x\nQUESTION: y?\n"


def test_paint_llm_block_custom_palette():
    tty = TTY()
    ui.paint_llm_block("hi", {"content": "magenta"}, tty)
    assert tty.getvalue() == "\x1b[35mhi\x1b[0m\n"


def test_markdown_in_llm_reply_printed_verbatim():
    pipe = io.StringIO()
    ui.paint_llm_block("**bold** `code` stays", ui.DEFAULT_LLM_COLORS, pipe)
    assert pipe.getvalue() == "**bold** `code` stays\n"


# --- operator question channel (spec: agent-loop-consent, design D6) ---


def test_render_question_on_tty_uses_palette():
    tty = TTY()
    ui.render_question(
        "Which init do you run?",
        [
            {"label": "systemd", "consequences": "rebuilds 12 packages"},
            {"label": "openrc", "consequences": "keeps the current queue"},
        ],
        ui.DEFAULT_LLM_COLORS,
        tty,
    )
    out = tty.getvalue()
    assert "\x1b[33mWhich init do you run?\x1b[0m" in out
    # decision block: blank line, bold-yellow banner, yellow body, green numbers
    assert f"\n\x1b[1;33m{ui.DECISION_BANNER}\x1b[0m\n" in out
    assert "\x1b[32m  1.\x1b[0m\x1b[33m systemd — rebuilds 12 packages\x1b[0m" in out
    assert "\x1b[32m  2.\x1b[0m\x1b[33m openrc — keeps the current queue\x1b[0m" in out
    assert out.endswith("\x1b[32m  2.\x1b[0m\x1b[33m openrc — keeps the current queue\x1b[0m\n\n")


def test_render_question_plain_in_pipe():
    pipe = io.StringIO()
    ui.render_question(
        "Which init?", [{"label": "systemd", "consequences": "rebuilds 12"}],
        ui.DEFAULT_LLM_COLORS, pipe,
    )
    assert pipe.getvalue() == (
        f"Which init?\n\n{ui.DECISION_BANNER}\n  1. systemd — rebuilds 12\n\n"
    )


def test_render_question_without_color_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    tty = TTY()
    ui.render_question("Which init?", [{"label": "s", "consequences": "c"}], None, tty)
    assert "\x1b" not in tty.getvalue()
    # the structural separation survives without color
    assert ui.DECISION_BANNER in tty.getvalue()


def test_render_question_empty_options_prints_only_question():
    pipe = io.StringIO()
    ui.render_question("Anything you know?", [], ui.DEFAULT_LLM_COLORS, pipe)
    # no options -> no decision block at all: no banner, no blank lines
    assert pipe.getvalue() == "Anything you know?\n"


def test_render_question_consequences_missing_or_custom_palette():
    pipe = io.StringIO()
    ui.render_question("q", [{"label": "  unmask  ", "consequences": "  "}], None, pipe)
    assert pipe.getvalue() == f"q\n\n{ui.DECISION_BANNER}\n  1. unmask\n\n"
    tty = TTY()
    ui.render_question("q", [{"label": "a", "consequences": "b"}], {"question": "off"}, tty)
    out = tty.getvalue()
    assert out.startswith("q\n")  # question off -> plain; the block keeps fixed colors
    assert "\x1b[32m  1.\x1b[0m\x1b[33m a — b\x1b[0m" in out


# --- decision-block chrome and kind scale (spec: console-output) ------------


def test_decision_helpers_painted_on_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    tty = TTY()
    assert ui.decision_banner_line(tty) == f"\x1b[1;33m{ui.DECISION_BANNER}\x1b[0m"
    assert ui.decision_choice(tty, "[1]", " Merge") == "\x1b[32m[1]\x1b[0m\x1b[33m Merge\x1b[0m"
    assert ui.decision_text(tty, "[c] own text") == "\x1b[33m[c] own text\x1b[0m"


def test_decision_helpers_plain_in_pipe_and_no_color(monkeypatch):
    pipe = io.StringIO()
    assert ui.decision_banner_line(pipe) == ui.DECISION_BANNER
    assert ui.decision_choice(pipe, "[1]", " Merge") == "[1] Merge"
    assert ui.decision_text(pipe, "[c] own text") == "[c] own text"
    monkeypatch.setenv("NO_COLOR", "1")
    tty = TTY()
    assert "\x1b" not in ui.decision_banner_line(tty)
    assert "\x1b" not in ui.decision_choice(tty, "[1]", " Merge")


def test_decision_banner_is_fixed_width_single_line():
    assert len(ui.DECISION_BANNER) == 40
    assert "\n" not in ui.DECISION_BANNER


def test_kind_sgr_importance_scale():
    red = ui.color_sgr("red")
    yellow = ui.color_sgr("yellow")
    cyan = ui.color_sgr("cyan")
    assert ui.kind_sgr("severity") == red
    assert ui.kind_sgr("dep-conflict") == red
    assert ui.kind_sgr("conflict") == red
    assert ui.kind_sgr("empty-update") == red
    assert ui.kind_sgr("masked") == yellow
    assert ui.kind_sgr("dep-required") == yellow
    assert ui.kind_sgr("config-updating") == yellow
    assert ui.kind_sgr("world-file") == yellow
    assert ui.kind_sgr("important") == cyan
    assert ui.kind_sgr("warning") == cyan


def test_kind_sgr_unknown_and_junk_paint_plain():
    assert ui.kind_sgr("other") == ""
    assert ui.kind_sgr("") == ""
    assert ui.kind_sgr(None) == ""
    assert ui.kind_sgr({"kind": "masked"}) == ""


def test_choice_prompt_styled_on_tty_plain_in_pipe():
    assert ui.choice_prompt(3, stream=TTY()) == "\x1b[1;33m[1..3] choose, [c] own text, [q] quit: \x1b[0m"
    assert ui.choice_prompt(1, stream=io.StringIO()) == "[1] choose, [c] own text, [q] quit: "


def test_choice_prompt_default_stream_resolved_at_call_time(monkeypatch):
    tty = TTY()
    monkeypatch.setattr(ui.sys, "stdout", tty)
    assert ui.choice_prompt(2).startswith("\x1b[1;33m[1..2]")


def test_echo_answer_goes_to_stream():
    tty = TTY()
    ui.echo_answer("openrc — keeps the current queue", ui.DEFAULT_LLM_COLORS, tty)
    assert tty.getvalue() == "\x1b[36m> openrc — keeps the current queue\x1b[0m\n"
    pipe = io.StringIO()
    ui.echo_answer("use --backtrack=50", ui.DEFAULT_LLM_COLORS, pipe)
    assert pipe.getvalue() == "> use --backtrack=50\n"


# --- human-readable request dump (spec: progress-logging, design D1-D5) ----


def _basic_payload():
    return {
        "model": "qwen3.8",
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are an assistant for Gentoo"},
            {"role": "user", "content": "Incident context follows\nsecond line"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "pretend_emerge",
                    "description": "simulate an emerge run",
                    "parameters": {"properties": {"category": {}, "flags": {}}},
                },
            }
        ],
    }


def _assert_no_json_syntax(lines):
    for line in lines:
        assert "{" not in line and "}" not in line, line
        assert '\\"' not in line, line


def test_render_request_header_line():
    lines = ui.render_request(_basic_payload())
    first = lines[0]
    assert first.startswith("request: ")
    assert "model=qwen3.8" in first and "temperature=0.2" in first
    assert "messages=2" in first and "tools=1" in first
    assert "body=" in first and first.endswith("chars")


def test_render_request_one_block_per_message():
    lines = ui.render_request(_basic_payload())
    system = next(l for l in lines if "[1] system" in l)
    assert "· 31 chars: You are an assistant for Gentoo" in system
    user = next(l for l in lines if "[2] user" in l)
    assert "Incident context follows⏎second line" in user  # newlines fold to ⏎
    _assert_no_json_syntax(lines)


def test_render_request_tool_calls_and_tool_result():
    payload = _basic_payload()
    payload["messages"] += [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "pretend_emerge",
                        "arguments": '{"category": "app-editors/vim"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_0fef95",
            "content": json.dumps({"ok": True, "stderr_tail": "!!! PORTAGE " * 400}),
        },
    ]
    lines = ui.render_request(payload)
    call = next(l for l in lines if "tool_calls" in l)
    assert "[3] assistant" in call
    assert "pretend_emerge(category=app-editors/vim)" in call
    result = next(l for l in lines if "[4] tool" in l)
    assert "call_0fef95" in result
    assert f"· {ui._dump_num(len(payload['messages'][3]['content']))} chars:" in result
    assert "[capped, 4800 chars total]" in result  # the field cap is marked
    _assert_no_json_syntax(lines)


def test_render_request_lists_tools_with_descriptions():
    payload = _basic_payload()
    payload["tools"].append({"type": "function", "function": {"name": "read_log"}})
    lines = ui.render_request(payload)
    assert "  tool[1/2] pretend_emerge — simulate an emerge run (args: category, flags)" in lines
    assert any(l.startswith("  tool[2/2] read_log") for l in lines)


def test_render_request_unknown_fields_stay_key_value():
    payload = _basic_payload()
    payload["mystery"] = {"deep": {"deeper": "some value"}, "list": [1, "two"]}
    lines = ui.render_request(payload)
    assert any(l.startswith("  mystery:") for l in lines)
    assert any('deeper="some value"' in l for l in lines)
    assert any("deep=" in l or "deep:" in l for l in lines)
    _assert_no_json_syntax(lines)


def test_render_request_content_list_parts():
    payload = _basic_payload()
    payload["messages"] = [
        {"role": "user", "content": [{"type": "text", "text": "part one"},
                                      {"type": "text", "text": "part two"}]}
    ]
    lines = ui.render_request(payload)
    block = next(l for l in lines if "[1] user" in l)
    assert "part one" in block and "part two" in block
    _assert_no_json_syntax(lines)


def test_render_request_total_cap_marks_truncation():
    payload = _basic_payload()
    payload["messages"] = [
        {"role": "user", "content": f"message {i}: " + "z" * 60} for i in range(64)
    ]
    lines = ui.render_request(payload)
    marker = lines[-1]
    assert marker.startswith("dump truncated: shown ")
    assert " of " in marker
    shown, total = (int(n) for n in re.findall(r"\d+", marker))
    assert 0 < shown < total


def test_render_request_no_truncation_marker_for_small_payload():
    assert not any("dump truncated" in l for l in ui.render_request(_basic_payload()))


def test_render_request_masks_api_key_everywhere():
    key = "secret-token-42"
    payload = _basic_payload()
    payload["messages"] = [
        {"role": "user", "content": "leaked " + key + " in text"},
        {"role": "user", "content": key},
        {"role": "user", "content": "long " + key + " " + "y" * 500},  # key near the cap
    ]
    lines = ui.render_request(payload, api_key=key)
    joined = "\n".join(lines)
    assert key not in joined
    assert "***" in joined
    assert "[capped, 521 chars total]" in joined  # sizes stay truthful
    _assert_no_json_syntax(lines)


def test_render_request_field_limits_are_configurable():
    lines = ui.render_request(_basic_payload(), field_limit=10, total_limit=200)
    assert any("[capped," in l for l in lines)
    assert lines[-1].startswith("dump truncated:")
