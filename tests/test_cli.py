import builtins
import json

import pytest

from emerge_ai import cli


@pytest.fixture
def ok_compat(monkeypatch):
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.0.82.2")


def test_passthrough_stdio_and_rc(emerge_stub, capfd, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "17")
    rc = cli.main(["--noninteractive", "-uDN", "@world"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    captured = capfd.readouterr()
    assert rc == 17
    # plan-before-plain-merge: the plan phase fails terminally; its emerge
    # output mirrors to stderr so merge stdout stays a pure passthrough
    assert "STUB-OUT line1" in captured.err
    assert captured.out == ""
    # emerge's stderr is routed to our stderr (split-emerge-stderr); the merged
    # buffer still carries both for incident context
    assert "STUB-ERR line1" in captured.err
    assert "STUB-ERR line1" not in captured.out
    assert calls() == [["-uDN", "@world", "--pretend"]]  # plan died; merge never ran


def test_version_gate_blocks_any_emerge_call(emerge_stub, monkeypatch, capsys, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.1.0")
    rc = cli.main(["-p", "sys-apps/portage"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 4
    assert calls() == []
    err = capsys.readouterr().err
    assert "3.1.0" in err and "emerge-ai" in err


def test_pretend_prints_verbatim_runs_once(emerge_stub, capsys, ok_compat, tmp_path):
    binary, calls = emerge_stub
    rc = cli.main(["-p", "sys-apps/portage"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "STUB-OUT line1" in out
    assert calls() == [["-p", "sys-apps/portage"]]


def test_ask_denied_never_merges(emerge_stub, ok_compat, monkeypatch, capsys, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    rc = cli.main(["-a", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert calls() == [["sys-apps/foo", "--pretend"]]
    assert "aborted" in capsys.readouterr().err


def test_ask_flag_never_reaches_emerge_plan_phase(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    assert cli.main(["-ap", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert calls() == [["-p", "sys-apps/foo"]]
    for call in calls():
        assert "-a" not in call and "--ask" not in call


def _no_stdin(monkeypatch):
    def boom(prompt=""):
        raise AssertionError("question must not be asked when --pretend wins")

    monkeypatch.setattr(builtins, "input", boom)


def test_ask_pretend_combo_never_merges_or_asks(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    _no_stdin(monkeypatch)
    rc = cli.main(["-a", "-p", "sys-apps/foo"], emerge_binary=binary,
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert calls() == [["-p", "sys-apps/foo"]]  # -a dropped, -p kept, single plan-phase call
    out = capsys.readouterr()
    assert "STUB-OUT" in out.out  # pretend output printed verbatim
    assert "--pretend takes precedence over --ask" in out.err


def test_ask_pretend_cluster_and_order_equivalent(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    _no_stdin(monkeypatch)
    assert cli.main(["-ap", "sys-apps/foo"], emerge_binary=binary,
                    runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert cli.main(["-p", "-a", "sys-apps/foo"], emerge_binary=binary,
                    runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert calls() == [["-p", "sys-apps/foo"], ["-p", "sys-apps/foo"]]  # one plan call each, no merge


def test_ask_pretend_propagates_plan_failure(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    _no_stdin(monkeypatch)
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "1")
    rc = cli.main(["-a", "-p", "sys-apps/foo"], emerge_binary=binary,
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 1
    assert calls() == [["-p", "sys-apps/foo"]]  # incident path, still no merge attempt


def test_ask_eof_denied(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub

    def _eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _eof)
    assert cli.main(["--ask", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert len(calls()) == 1


def test_ask_confirmed_merges_without_ask_flags(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    assert cli.main(["-a", "-N", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert calls() == [["-N", "sys-apps/foo", "--pretend"], ["-N", "sys-apps/foo"]]


def test_plan_failure_consults_agent(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_ERR", "slot conflict: dev-util/glslang")
    (tmp_path / "emerge-ai.json").write_text('{"endpoint": "http://127.0.0.1:9/v1"}')
    seen = []

    def agent(incident):
        seen.append(incident)
        return "PROPOSAL: pin glslang"

    rc = cli.main(
        ["-p", "sys-apps/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
        agent_fn=agent,
    )
    assert rc == 1
    assert seen and seen[0]["class"] == "plan-failed"
    assert "slot conflict" in seen[0]["stderr_tail"]
    assert "PROPOSAL: pin glslang" in capsys.readouterr().err


def test_ask_cluster_av_intercepted(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    assert cli.main(["-av", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None) == 0
    assert calls() == [["-v", "sys-apps/foo", "--pretend"]]


def test_ask_noninteractive_proceeds_without_prompt(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub

    def _boom(prompt=""):
        raise AssertionError("must not prompt in --noninteractive")

    monkeypatch.setattr(builtins, "input", _boom)
    rc = cli.main(["--noninteractive", "-a", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert calls()[-1] == ["sys-apps/foo"]


# --- meta flags: --version/-V/--help are recognized only as argv[0] (spec: cli-compat) ---


def test_version_meta_flag_prints_and_skips_emerge(emerge_stub, ok_compat, capsys, tmp_path):
    binary, calls = emerge_stub
    for meta in ("--version", "-V"):
        rc = cli.main([meta], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "emerge-ai" in out and "3.0.82.2" in out
    assert calls() == []


def test_help_meta_flag_prints_own_flags_and_skips_emerge(emerge_stub, ok_compat, capsys, tmp_path):
    binary, calls = emerge_stub
    rc = cli.main(["--help"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "--noninteractive" in out and "--changelog" in out
    assert calls() == []


def test_meta_flag_at_nonzero_position_passes_through(emerge_stub, ok_compat, capsys, tmp_path):
    binary, calls = emerge_stub
    rc = cli.main(["-p", "--help"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert calls() == [["-p", "--help"]]
    assert "own flags" not in capsys.readouterr().out


def test_meta_flags_work_with_incompatible_portage(emerge_stub, monkeypatch, capsys, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.1.0")
    assert cli.main(["--help"], emerge_binary=binary, runs_dir=str(tmp_path)) == 0
    assert "--noninteractive" in capsys.readouterr().out
    assert cli.main(["-V"], emerge_binary=binary, runs_dir=str(tmp_path)) == 0
    assert "emerge-ai" in capsys.readouterr().out
    assert calls() == []


def test_changelog_bypasses_version_gate(emerge_stub, monkeypatch, capsys, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.1.0")
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"gh_repos": [], "git_urls": [], "news_dir": "%s"}' % (tmp_path / "no-news"))
    rc = cli.main(["--changelog"], emerge_binary=binary, config_path=str(cfg), runs_dir=str(tmp_path))
    assert rc == 0
    assert calls() == []
    err = capsys.readouterr().err
    assert "incompatible" not in err.lower()


# --- verbose / reasoning visibility (spec: config-prompts «Вывод рассуждений») ---


def test_verbose_cluster_keeps_v_for_emerge(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    prompts = []
    monkeypatch.setattr(builtins, "input", lambda prompt="": prompts.append(prompt) or "y")
    rc = cli.main(["-av", "sys-apps/x"], emerge_binary=binary, runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert prompts  # the -a inside the cluster was recognized as ask
    assert calls() == [["-v", "sys-apps/x", "--pretend"], ["-v", "sys-apps/x"]]  # -v survives everywhere


def test_maybe_agent_gated_on_show_reasoning(monkeypatch, tmp_path):
    from emerge_ai import state
    from emerge_ai.flags import Mode

    captured = []

    class Boom:
        def __init__(self, cfg, **kw):
            captured.append(kw)
            raise RuntimeError("construction stopped")

    monkeypatch.setattr(cli, "LLMClient", Boom)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"endpoint": "http://x/v1"}')
    cfg.chmod(0o600)
    run = state.new_run(["-v"], Mode())
    run.incident = {"class": "block"}
    cli._maybe_agent(run, str(cfg))
    assert captured[-1] == {"show_reasoning": False}
    cli._maybe_agent(run, str(cfg), show_reasoning=True)
    assert captured[-1] == {"show_reasoning": True}


# --- interactive operator question channel reaches the agent (spec: agent-loop-consent) ---


class _TTYStdin:
    def isatty(self) -> bool:
        return True


class _PipeStdin:
    def isatty(self) -> bool:
        return False


@pytest.fixture
def agent_spy(tmp_path):
    """Endpoint configured; fake agent records (incident class, interactive flag)."""
    (tmp_path / "emerge-ai.json").write_text('{"endpoint": "http://127.0.0.1:9/v1"}')
    seen: list = []

    def agent(incident, interactive=None):
        seen.append((incident["class"], interactive))
        return "PROPOSAL: pin glslang"

    return seen, agent


def test_agent_gets_no_questions_in_pretend(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_spy):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())  # a TTY does not matter under -p
    seen, agent = agent_spy
    rc = cli.main(["-p", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, agent_fn=agent)
    assert rc == 1
    assert seen == [("plan-failed", False)]


def test_agent_gets_no_questions_when_noninteractive(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_spy):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())
    seen, agent = agent_spy
    rc = cli.main(["--noninteractive", "-p", "sys-apps/foo"], emerge_binary=binary,
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None, agent_fn=agent)
    assert rc == 1
    assert seen == [("plan-failed", False)]


def test_agent_gets_no_questions_without_tty(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_spy):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setattr(cli.sys, "stdin", _PipeStdin())
    seen, agent = agent_spy
    rc = cli.main(["app-misc/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, agent_fn=agent)
    assert rc == 1
    assert seen and seen[0][1] is False


def test_agent_can_ask_on_tty_without_flags(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_spy):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())
    seen, agent = agent_spy
    rc = cli.main(["app-misc/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, agent_fn=agent)
    assert rc == 1
    assert seen and seen[0][1] is True  # merge-fail without -a


def test_agent_can_ask_after_failed_ask_merge(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_spy):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())
    seen, agent = agent_spy
    rc = cli.main(["-a", "app-misc/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, agent_fn=agent)
    assert rc == 1
    assert seen and seen[-1][1] is True  # merge-fail after -a


def test_legacy_one_argument_agent_fn_still_works_and_never_reads_stdin(
    emerge_stub, ok_compat, monkeypatch, tmp_path, capsys
):
    binary, _ = emerge_stub
    (tmp_path / "emerge-ai.json").write_text('{"endpoint": "http://127.0.0.1:9/v1"}')
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())

    def _boom(prompt=""):
        raise AssertionError("plan-failed with -p must not read stdin")

    monkeypatch.setattr(builtins, "input", _boom)
    seen = []

    def legacy_agent(incident):
        seen.append(incident)
        return "PROPOSAL: legacy"

    rc = cli.main(["-p", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, agent_fn=legacy_agent)
    assert rc == 1
    assert seen and seen[0]["class"] == "plan-failed"
    assert "PROPOSAL: legacy" in capsys.readouterr().err


def test_call_agent_fn_adapts_signature():
    calls = []

    def legacy(incident):
        calls.append(("legacy",))
        return "p1"

    def modern(incident, interactive=False):
        calls.append(("modern", interactive))
        return "p2"

    def star(incident, **kw):
        calls.append(("star", kw.get("interactive")))
        return "p3"

    assert cli._call_agent_fn(legacy, {"class": "x"}, True) == "p1"
    assert cli._call_agent_fn(modern, {"class": "x"}, True) == "p2"
    assert cli._call_agent_fn(star, {"class": "x"}, False) == "p3"
    assert calls == [("legacy",), ("modern", True), ("star", False)]


NOT_SYSTEMD = lambda: False


def test_openrc_host_refuses_plain_install(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("stdin read"))
    rc = cli.main(["sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, systemd_check=NOT_SYSTEMD)
    assert rc == 6
    assert calls() == []  # emerge was never started, system untouched
    err = capsys.readouterr().err
    assert "systemd hosts only" in err


def test_openrc_host_refuses_ask_before_plan(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    rc = cli.main(["-a", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, systemd_check=NOT_SYSTEMD)
    assert rc == 6  # -a can mutate: refused even before the plan phase
    assert calls() == []


def test_openrc_host_pretend_warns_and_proceeds(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    rc = cli.main(["-p", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, systemd_check=NOT_SYSTEMD)
    assert rc == 0
    assert calls() == [["-p", "sys-apps/foo"]]
    out = capsys.readouterr()
    assert "STUB-OUT" in out.out
    assert "no systemd detected" in out.err


def test_openrc_host_ask_pretend_combo_warns_only(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    rc = cli.main(["-a", "-p", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None, systemd_check=NOT_SYSTEMD)
    assert rc == 0  # pretend dominates => read-only => warn, no refusal
    assert calls() == [["-p", "sys-apps/foo"]]
    assert "no systemd detected" in capsys.readouterr().err


def test_openrc_host_changelog_warns_and_proceeds(emerge_stub, ok_compat, tmp_path, capsys):
    news = tmp_path / "news"
    news.mkdir()
    (news / "2026-01-01-x.news").write_text("Title: T\nBody.\n")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"news_dir": str(news), "gh_repos": [], "git_urls": []}))
    rc = cli.main(["--changelog"], emerge_binary="false", runs_dir=str(tmp_path),
                  config_path=str(cfg), systemd_check=NOT_SYSTEMD)
    assert rc == 0
    out = capsys.readouterr()
    assert "no systemd detected" in out.err and "changelog digest" in out.out


def test_meta_version_never_needs_systemd(tmp_path):
    # --version exits in _meta_command before any init probe
    assert cli.main(["--version"], runs_dir=str(tmp_path)) in (0, 3)


def test_plain_world_doctor_stderr_stdout_clean(emerge_stub, ok_compat, tmp_path, capfd):
    """run-reporting «Обычный запуск без флагов»: doctor в stderr, stdout — только emerge."""
    from emerge_ai.plan import Plan, PlanEntry

    binary, calls = emerge_stub
    rc = cli.main(
        ["--noninteractive", "-uDN", "@world"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-apps/baselayout-2.17", 1, "hint")]),
    )
    assert rc == 0
    captured = capfd.readouterr()
    assert "STUB-OUT line1" in captured.out  # merge passthrough intact
    assert "emerge-ai plan digest:" in captured.err  # enrichment lives on stderr
    assert "critical subsystem" in captured.err  # doctor warning about the tier-1 entry
    assert captured.err.count("STUB-OUT") == 1  # only the plan-run stdout mirrored here; merge's stays in stdout
    assert captured.err.index("STUB-OUT") < captured.err.index("emerge-ai plan digest:")  # order: emerge, then enrichment
    assert calls() == [["-uDN", "@world", "--pretend"], ["-uDN", "@world"]]


def _pretend_stub(tmp_path, text):
    import stat

    path = tmp_path / "emerge-pretend"
    path.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stdout.write(%r)\nsys.exit(0)\n" % text
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_plan_reuses_pretend_output_no_resolver(tmp_path, ok_compat, capfd):
    """avoid-double-resolve: план строится из перехваченного -p вывода, фолбэк-резолвер не зван."""
    pretend = (
        "These are the packages that would be merged, in order:\n\n"
        "Calculating dependencies... done!\n"
        "[ebuild   R    ] sys-libs/glibc-2.42::gentoo  USE=\"nls\" 0 KiB\n"
        "[ebuild   U    ] [app-editors/vim-9.1:0::gentoo] USE=\"X\" 1 KiB\n\n"
        "Total: 2 packages, in 1 segment\n"
    )
    binary = _pretend_stub(tmp_path, pretend)
    calls = []
    rc = cli.main(["--noninteractive", "-uDN", "@world"], emerge_binary=binary,
                  runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: calls.append(1) or None)
    assert rc == 0
    assert calls == []  # pretend output parsed; no second resolve
    err = capfd.readouterr().err
    digest_line = next(l for l in err.splitlines() if "pkg(s)" in l)
    assert "sys-libs/glibc-2.42" in digest_line and "app-editors/vim-9.1" in digest_line
    assert "::" not in digest_line and "[" not in digest_line  # cleaned CPVs in digest


def test_plan_falls_back_to_resolver_on_quiet_output(tmp_path, ok_compat):
    binary = _pretend_stub(tmp_path, "app-misc/foo-1.0\n")  # emerge -qq style
    seen = []

    def plan_fn(args, svc):
        seen.append(list(args))
        from emerge_ai.plan import Plan, PlanEntry

        return Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")])

    rc = cli.main(["--noninteractive", "app-misc/foo"], emerge_binary=binary,
                  runs_dir=str(tmp_path), plan_fn=plan_fn)
    assert rc == 0
    assert seen == [["app-misc/foo"]]  # exactly one fallback resolve
