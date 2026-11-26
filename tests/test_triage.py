"""Deterministic plan-phase triage (spec: plan-triage) on live-shaped output:
the fixtures below mirror a real `emerge-ai @world -uDN --keep-going -av` run
(rc 0, edk2/qemu conflict, yazi skipped via the masked jemalloc, world-file
problem, IMPORTANT config line, Total: 0 packages)."""

from emerge_ai import triage

# real degraded plan: rc == 0, but nothing is merged and four problems speak
LIVE_DEGRADED = """These are the packages that would be merged, in order:

Calculating dependencies... done!

!!! Problems have been detected with your world file
!!! Please run emaint --fix world
WARNING: One or more updates/rebuilds have been skipped due to a dependency conflict:
app-container/edk2-bin:0
  (app-container/edk2-bin-20240509-r1:0/0::gentoo, ebuild scheduled for merge) conflicts with
    (app-emulation/qemu-8.2.0-r5:0/0::gentoo, installed) which blocks app-container/edk2-bin
app-editors/yazi:0
  (app-editors/yazi-0.4.3:0/0::gentoo, ebuild scheduled for merge) depends on
    >=dev-libs/jemalloc-5.3.1:0/0=::gentoo which is not installed
    (dev-libs/jemalloc-5.4.0-r2:0/0::gentoo, masked by: ~amd64 keyword)
 * IMPORTANT: config file '/etc/portage/portage/lto' needs updating - please use 'etc-update'

Total: 0 packages
"""

LIVE_CLEAN = """These are the packages that would be merged, in order:

Calculating dependencies... done!
[ebuild   R    ] app-editors/vim-9.1::gentoo  USE="X python" 0 KiB
[ebuild     U  ] dev-libs/jemalloc-5.3.1::gentoo [5.3.0::gentoo] 0 KiB

Total: 2 packages
"""

UPDATE_ARGV = ["-uDN", "@world", "--keep-going", "-av"]


def _kinds(verdict):
    return [f.kind for f in verdict.findings]


def test_live_degraded_run_verdict_and_findings():
    v = triage.scan(LIVE_DEGRADED, UPDATE_ARGV)
    kinds = _kinds(v)
    assert v.degraded
    assert "world-file" in kinds
    assert "dep-conflict" in kinds
    assert "conflict" in kinds
    assert "masked" in kinds
    assert "config-updating" in kinds
    assert "empty-update" in kinds


def test_findings_carry_culprit_cpv_and_quoted_evidence():
    v = triage.scan(LIVE_DEGRADED, UPDATE_ARGV)
    masked = next(f for f in v.findings if f.kind == "masked")
    assert masked.cpv == "dev-libs/jemalloc-5.4.0-r2"
    assert "masked by: ~amd64 keyword" in masked.evidence
    conflict = next(f for f in v.findings if f.kind == "conflict")
    assert conflict.cpv == "app-container/edk2-bin-20240509-r1"
    conflict_warn = next(f for f in v.findings if f.kind == "dep-conflict")
    assert conflict_warn.cpv == "app-container/edk2-bin"  # named on the next line


def test_clean_plan_no_findings_and_streams_identical():
    v = triage.scan(LIVE_CLEAN, UPDATE_ARGV)
    assert v.status == triage.CLEAN
    assert v.findings == []
    assert triage.render_report(v) == []
    assert triage.build_slice(LIVE_CLEAN) == ""


def test_empty_plan_without_update_request_is_clean():
    v = triage.scan("Total: 0 packages\n", ["app-misc/foo"])
    assert v.status == triage.CLEAN
    v2 = triage.scan("Total: 0 packages\n", ["-uDN", "@world"])
    assert v2.degraded
    assert _kinds(v2) == ["empty-update"]
    assert "Total: 0 packages" in v2.findings[0].evidence


def test_empty_plan_with_long_update_flags():
    v = triage.scan("Total: 0 packages\n", ["--update", "--deep", "--newuse", "@world"])
    assert _kinds(v) == ["empty-update"]


def test_scan_strips_ansi_before_matching():
    colored = "\x1b[1;31m!!!\x1b[0m Problems have been detected with your world file\n"
    v = triage.scan(colored, ["app-misc/foo"])
    assert _kinds(v) == ["world-file"]
    assert "\x1b" not in v.findings[0].evidence


def test_slice_keeps_problems_and_total_excludes_use_sheets():
    use_sheets = "\n".join(
        f"[ebuild     U  ] cat/pkg{i}-1.{i}::gentoo USE=\"aa bb cc dd ee ff gg hh ii jj kk ll mm nn oo pp\""
        for i in range(400)
    )
    text = use_sheets + "\n" + LIVE_DEGRADED
    s = triage.build_slice(text)
    assert "masked by: ~amd64 keyword" in s
    assert "conflicts with" in s
    assert "Total: 0 packages" in s
    assert 'USE="aa bb' not in s
    assert "cat/pkg7-" not in s
    assert len(s.encode("utf-8")) <= triage.SLICE_CAP_BYTES


def test_slice_cap_banner_points_at_the_artifact():
    text = LIVE_DEGRADED * 40
    s = triage.build_slice(text, cap_bytes=600, path="/var/lib/emerge-ai/runs/r1/plan-output.txt")
    assert len(s.encode("utf-8")) <= 600
    assert s.endswith("[capped; полный текст: /var/lib/emerge-ai/runs/r1/plan-output.txt]")


def test_slice_overlapping_windows_are_merged_once():
    text = (
        "!!! first\nnoise a\nnoise b\n!!! second\nplain line\nnoise c\nnoise d\n"
    )
    s = triage.build_slice(text)
    assert s.count("!!! first") == 1
    assert s.count("!!! second") == 1
    assert "noise a" in s  # context window
    assert "..." not in s  # one merged block, no separator


def test_candidates_split_executable_from_manual():
    v = triage.scan(LIVE_DEGRADED, UPDATE_ARGV)
    cands = triage.candidates(v.findings)
    by_kind = {c["kind"]: c for c in cands}
    assert by_kind["accept_keywords"]["executable"] is True
    assert by_kind["accept_keywords"]["text"] == "=dev-libs/jemalloc-5.4.0-r2 ~amd64"
    assert by_kind["etc-update"]["executable"] is True
    assert "/etc/portage/portage/lto" in by_kind["etc-update"]["text"]
    assert by_kind["emaint"]["executable"] is False
    assert by_kind["world-review"]["executable"] is False


def test_render_report_advisory_only_no_questions():
    v = triage.scan(LIVE_DEGRADED, UPDATE_ARGV)
    lines = triage.render_report(v, "/runs/r1/plan-output.txt", for_pretend=True)
    report = "\n".join(lines)
    assert "plan DEGRADED despite exit code 0" in report
    assert "=dev-libs/jemalloc-5.4.0-r2 ~amd64" in report
    assert "executed when the run is not --pretend" in report
    assert "not executable by emerge-ai yet" in report
    assert "/runs/r1/plan-output.txt" in report
    assert "?" not in report  # advisory: zero questions


def test_plan_incident_references_full_text_without_truncation():
    v = triage.scan(LIVE_DEGRADED, UPDATE_ARGV)
    s = triage.build_slice(LIVE_DEGRADED, path="/runs/r1/plan-output.txt")
    inc = triage.plan_incident(UPDATE_ARGV, v, s, log_path="/runs/r1/plan-output.txt")
    assert inc["class"] == "plan-degraded"
    assert inc["returncode"] == 0
    assert inc["log_path"] == "/runs/r1/plan-output.txt"
    assert inc["findings"][0]["kind"] == "world-file"
    # the inline evidence is the capped slice, not a stderr_tail truncation
    assert inc["stderr_tail"] == s


def test_incident_classification_plan_degraded_only_at_rc_zero():
    from emerge_ai.incident import build_incident

    inc = build_incident(0, LIVE_DEGRADED, UPDATE_ARGV, log_path="/runs/r1/plan-output.txt")
    assert inc["class"] == "plan-degraded"
    assert inc["log_path"] == "/runs/r1/plan-output.txt"
    assert inc["stderr_tail"] == LIVE_DEGRADED  # no 4000-char tail cut for this class

    # a non-zero run with the same evidence keeps its structural class
    hard = LIVE_DEGRADED + "\n!!! ERROR: app-misc/foo-1.2.3 failed (compile phase):\n"
    inc2 = build_incident(1, hard, UPDATE_ARGV)
    assert inc2["class"] != "plan-degraded"
    assert len(inc2["stderr_tail"]) <= 4000
