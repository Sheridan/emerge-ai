import io

from emerge_ai.doctor import doctor_report, is_mass_update
from emerge_ai.enrich import format_duration, parse_genlop, plan_digest
from emerge_ai.plan import Plan, PlanEntry


class TTY(io.StringIO):
    def isatty(self):
        return True

GENLOP_SAMPLE = (
    "\x1b[1;34m * sys-apps/portage\n\n\x1b[0m"
    "    Sat Mar 19 14:23:24 2022 >>>\x1b[1;32m sys-apps/portage-3.0.30-r1\n"
    "\x1b[0m       merge time: \x1b[1;32m9\x1b[0m seconds.\n"
    "    Tue Jan 10 12:00:00 2023 >>> sys-apps/portage-3.0.45\n"
    "      merge time: 1 hours 2 minutes 5 seconds.\n"
)


def test_parse_genlop_last_entry_seconds():
    assert parse_genlop(GENLOP_SAMPLE) == 3600 + 120 + 5


def test_parse_genlop_absent():
    assert parse_genlop("no merge data") is None


def test_format_duration():
    assert format_duration(3661) == "1h 1min 1s"
    assert format_duration(0) == "0s"


def _plan():
    return Plan(
        entries=[
            PlanEntry("sys-libs/glibc-2.42", 1, "hint"),
            PlanEntry("app-editors/vim-9.1", 5, "llm"),
        ]
    )


def test_plan_digest_lists_tiers_and_gaps():
    digest = plan_digest(_plan(), estimate=lambda cpv: 90 if "glibc" in cpv else None)
    assert "tier 1: 1 pkg(s)" in digest
    assert "1min 30s" in digest
    assert "without genlop data" in digest
    assert "lower bound" in digest


def test_doctor_warns_on_critical_and_silent_on_rest_only():
    warnings = doctor_report(_plan(), estimate=lambda cpv: 60)
    assert any("sys-libs/glibc-2.42" in w for w in warnings)
    quiet = Plan(entries=[PlanEntry("app-editors/vim-9.1", 5, "llm")])
    assert doctor_report(quiet, estimate=lambda cpv: 1) == []


def test_is_mass_update():
    assert is_mass_update(["-uDN", "@world"]) is True
    assert is_mass_update(["sys-apps/foo"], plan=_plan()) is False
    big = Plan(entries=[PlanEntry(f"c/p{i}", 5, "hint") for i in range(60)])
    assert is_mass_update([], plan=big) is True


def test_plan_digest_tier_gradient_on_tty_plain_on_pipe():
    tty = TTY()
    digest = plan_digest(_plan(), estimate=None, stream=tty)
    assert "\x1b[31m  tier 1:" in digest
    assert "\x1b[2m  tier 5:" in digest
    assert digest.count("\x1b[0m") == 2
    plain = plan_digest(_plan(), estimate=None, stream=io.StringIO())
    assert "\x1b" not in plain and "tier 1: 1 pkg(s)" in plain


def test_doctor_report_tier_gradient_on_tty_plain_on_pipe():
    tty = TTY()
    report = doctor_report(_plan(), estimate=lambda cpv: 60, stream=tty)
    warning = next(l for l in report if "sys-libs/glibc-2.42" in l)
    assert warning.startswith("\x1b[31m") and warning.endswith("\x1b[0m")
    header = next(l for l in report if "doctor" in l)
    assert "\x1b" not in header
    plain = doctor_report(_plan(), estimate=lambda cpv: 60, stream=io.StringIO())
    assert all("\x1b" not in l for l in plain)
