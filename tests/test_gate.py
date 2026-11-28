import io
import json

import pytest

from aimerge import ui
from aimerge.gate import Variant, autonomy_decision, gate, render


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def scripted(*answers):
    it = iter(answers)

    def fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return fn


def audit_lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def variants(actions):
    return [
        Variant("retry", "retry merge", pros=["simple"], cons=[], risks=["glibc tier 1"],
                tiers=(1,), action=lambda: actions.append("retry")),
        Variant("skip", "skip package --exclude", pros=["unblocks world"], risks=["pkg tier 5"],
                tiers=(5,), action=lambda: actions.append("skip")),
        Variant("rollback", "rollback to pre-merge state", kind="rollback",
                risks=["tier 1 restore"], tiers=(1,), action=lambda: actions.append("rollback")),
    ]


def test_render_shows_pros_cons_risks_with_tiers():
    text = render(variants([]))
    assert "+ simple" in text and "- " not in text.split("simple")[1].split("\n")[0]
    assert "! risk: glibc tier 1" in text
    assert "[c]" in text and "[q]" in text


# --- decision-block highlighting (spec: console-output, decision highlight) ---


def test_render_decision_block_painted_on_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    tty = TTY()
    text = render(variants([]), stream=tty)
    assert f"\x1b[1;33m{ui.DECISION_BANNER}\x1b[0m" in text
    assert "\x1b[32m[1]\x1b[0m\x1b[33m retry merge  (fix)\x1b[0m" in text
    assert "\x1b[33m      + simple\x1b[0m" in text
    assert "\x1b[33m      ! risk: glibc tier 1\x1b[0m" in text
    assert "\x1b[33m[c] propose your own text   [q] quit (no changes)\x1b[0m" in text
    lines = text.split("\n")
    assert lines[0] == "" and lines[-1] == ""  # blank separation around the block


def test_render_decision_block_plain_in_pipe():
    pipe = io.StringIO()
    text = render(variants([]), stream=pipe)
    assert "\x1b" not in text
    lines = text.split("\n")
    assert lines[0] == "" and lines[1] == ui.DECISION_BANNER
    assert lines[2] == "[1] retry merge  (fix)"
    assert lines[-1] == ""


def test_apply_only_after_explicit_yes(tmp_path):
    actions = []
    ap = tmp_path / "audit.log"
    res = gate(variants(actions), mode={}, confirm_fn=lambda p: False,
               input_fn=scripted("1"), audit_path=ap)
    assert res["status"] == "declined" and actions == []
    res = gate(variants(actions), mode={}, confirm_fn=lambda p: True,
               input_fn=scripted("2"), audit_path=ap)
    assert res["status"] == "applied" and actions == ["skip"]
    dec = audit_lines(ap)
    assert [d["decision"] for d in dec] == ["declined", "apply"]


def test_custom_text_returns_for_second_round(tmp_path):
    actions = []
    res = gate(variants(actions), mode={}, confirm_fn=lambda p: True,
               input_fn=scripted("c", "I would just reboot", "1"),
               effects_fn=lambda t: f"EFFECTS: reboot kills sessions ({t})",
               audit_path=tmp_path / "a.log")
    assert res["status"] == "applied" and actions == ["retry"]
    assert not any("reboot" in json.dumps(a) for a in actions)


def test_invalid_choice_reasks_then_quit_eof(tmp_path):
    actions = []
    res = gate(variants(actions), mode={}, confirm_fn=lambda p: True,
               input_fn=scripted("9", "zzz"), audit_path=tmp_path / "a.log")
    assert res["status"] == "quit" and actions == []


def test_noninteractive_rest_tier_autofix(tmp_path):
    actions = []
    res = gate(variants(actions), mode={"noninteractive": True},
               confirm_fn=lambda p: pytest.fail("must not prompt"),
               input_fn=scripted("2"), audit_path=tmp_path / "a.log")
    assert res["status"] == "applied" and res["autonomy"] == "auto" and actions == ["skip"]


def test_noninteractive_critical_tier_denied_with_nonzero(tmp_path):
    actions = []
    res = gate(variants(actions), mode={"noninteractive": True},
               confirm_fn=lambda p: pytest.fail("must not prompt"),
               input_fn=scripted("1"), audit_path=tmp_path / "a.log")
    assert res["status"] == "denied" and res["exit"] == 6 and actions == []


def test_noninteractive_rollback_denied(tmp_path):
    actions = []
    res = gate(variants(actions), mode={"noninteractive": True},
               confirm_fn=lambda p: pytest.fail("must not prompt"),
               input_fn=scripted("3"), audit_path=tmp_path / "a.log")
    assert res["status"] == "denied" and actions == []


def test_responsibility_autonomous_everything_including_rollback(tmp_path):
    actions = []
    justifications = []
    res = gate(variants(actions), mode={"responsibility": True},
               confirm_fn=lambda p: pytest.fail("must not prompt"),
               input_fn=scripted("3"), audit_path=tmp_path / "a.log",
               echo=justifications.append)
    assert res["status"] == "applied" and actions == ["rollback"]
    assert any("--i-understand-what-i-am-doing" in j for j in justifications)


def test_unaffirmed_variants_have_no_system_effect():
    v = Variant("x", "t", tiers=(1,), action=lambda: pytest.fail("mutation leaked"))
    assert autonomy_decision({}, v)[0] == "ask"
    assert autonomy_decision({"noninteractive": True}, v)[0] == "deny"
    assert autonomy_decision({"responsibility": True}, v)[0] == "auto"


def test_risk_alias_mode_equals_long_flag():
    """wire-risk-flag: псевдоним — ровно тот же вход матрицы, что длинный флаг."""
    import dataclasses

    from aimerge.flags import parse_own_flags

    long_mode = dataclasses.asdict(
        parse_own_flags(["--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences"])[0]
    )
    alias_mode = dataclasses.asdict(parse_own_flags(["--i-understand-the-risks"])[0])
    v = Variant("fix", "f", tiers=(1,), action=lambda: None)
    assert autonomy_decision(alias_mode, v) == autonomy_decision(long_mode, v)
    assert autonomy_decision(alias_mode, v)[0] == "auto"
