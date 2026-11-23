import io

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
    assert "\x1b[36m  1. systemd — rebuilds 12 packages\x1b[0m" in out
    assert "\x1b[36m  2. openrc — keeps the current queue\x1b[0m" in out


def test_render_question_plain_in_pipe():
    pipe = io.StringIO()
    ui.render_question(
        "Which init?", [{"label": "systemd", "consequences": "rebuilds 12"}],
        ui.DEFAULT_LLM_COLORS, pipe,
    )
    assert pipe.getvalue() == "Which init?\n  1. systemd — rebuilds 12\n"


def test_render_question_without_color_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    tty = TTY()
    ui.render_question("Which init?", [{"label": "s", "consequences": "c"}], None, tty)
    assert "\x1b" not in tty.getvalue()


def test_render_question_empty_options_prints_only_question():
    pipe = io.StringIO()
    ui.render_question("Anything you know?", [], ui.DEFAULT_LLM_COLORS, pipe)
    assert pipe.getvalue() == "Anything you know?\n"


def test_render_question_consequences_missing_or_custom_palette():
    pipe = io.StringIO()
    ui.render_question("q", [{"label": "  unmask  ", "consequences": "  "}], None, pipe)
    assert pipe.getvalue() == "q\n  1. unmask\n"
    tty = TTY()
    ui.render_question("q", [{"label": "a", "consequences": "b"}], {"question": "off"}, tty)
    out = tty.getvalue()
    assert out.startswith("q\n")  # question off -> plain, options keep content color
    assert "\x1b[36m  1. a — b\x1b[0m" in out


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
