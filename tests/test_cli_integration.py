import builtins
import io
import json
import sys

import pytest

from emerge_ai import cli, state
from emerge_ai.flags import Mode
from emerge_ai.plan import Plan, PlanEntry
from emerge_ai.rollback import Protection


@pytest.fixture(autouse=True)
def _captured_output_is_always_plain(capsys):
    yield
    out, err = capsys.readouterr()
    assert "\x1b" not in out and "\x1b" not in err, "capsys output must never carry ANSI codes"


@pytest.fixture
def ok_compat(monkeypatch):
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.0.82.2")


def test_ask_shows_digest_and_runs_merge(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    plan = Plan(
        entries=[
            PlanEntry("app-editors/vim-9.1", 5, "hint"),
            PlanEntry("sys-libs/glibc-2.42", 1, "hint"),
        ]
    )
    rc = cli.main(
        ["-a", "app-editors/vim"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: plan,
        protect_fn=lambda run, plan: Protection(run_id=run.run_id),
    )
    assert rc == 0
    runs = list(tmp_path.glob("*.json"))
    assert len(runs) == 1
    saved = json.loads(runs[0].read_text())
    assert saved["state"] == "DONE"
    assert len(saved["plan"]) == 2


def test_world_mass_doctor_warns(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    plan = Plan(entries=[PlanEntry("sys-kernel/gentoo-sources-6.6", 1, "hint")])
    rc = cli.main(
        ["-a", "@world"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: plan,
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "doctor" in err and "sys-kernel/gentoo-sources-6.6" in err


def test_resume_without_run_passes_flag_to_emerge(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    rc = cli.main(
        ["--resume"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
    )
    assert rc == 0
    # plan-before-plain-merge: pretend resolve first, then the real emerge run
    assert calls() == [["--resume", "--pretend"], ["--resume"]]
    assert len(list(tmp_path.glob("*.json"))) == 1  # a fresh run is recorded
    assert "passing --resume to emerge" in capsys.readouterr().err


def test_capture_adds_color_flag_on_tty_stdout(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.delenv("NO_COLOR", raising=False)

    class TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdout", TTY())
    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
    )
    assert rc == 0
    assert calls()[0][0] == "--color=y"  # captured emerge never sees a TTY; color is explicit


def test_resume_reuses_incomplete_run_context(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    run = state.new_run(["--resume"], Mode(noninteractive=True))
    run.state = state.INCIDENT
    run.incident = {"class": "block"}
    state.save_run(run, runs_dir=tmp_path)

    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "--resume"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
    )
    assert rc == 0
    assert len(list(tmp_path.glob("*.json"))) == 1
    after = json.loads((tmp_path / f"{run.run_id}.json").read_text())
    assert after["state"] == "DONE"
    assert after["incident"] == {"class": "block"}
    assert "resuming run" in capsys.readouterr().err
    assert calls() == [["--pretend"], []]  # plan phase first, then the resumed merge


def _iter_input(*answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def test_protection_created_cleaned_on_success(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", _iter_input("y"))
    events = []
    prot = Protection(run_id="x", snapshot="/snap/r")
    rc = cli.main(
        ["-a", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: prot,
        cleanup_fn=lambda p: events.append(p) or ["cleaned"],
    )
    assert rc == 0
    assert events == [prot]
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["protection"]["snapshot"] == "/snap/r"
    assert saved["state"] == "DONE"


def test_protection_failure_denied_aborts_before_merge(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    # order (design D2): protect runs before "Proceed?", so the first answer
    # belongs to the recovery-point gate
    monkeypatch.setattr(builtins, "input", _iter_input("n"))
    failed = Protection(run_id="x", failed=True)
    rc = cli.main(
        ["-a", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: failed,
    )
    assert rc == 5
    assert calls() == [["sys-libs/glibc", "--pretend"]]


def test_protection_precedes_confirmation(emerge_stub, ok_compat, monkeypatch, tmp_path):
    """system-rollback «Триггер защиты»: точка создаётся до ответа на «Proceed?»."""
    binary, calls = emerge_stub
    order = []
    monkeypatch.setattr(builtins, "input", lambda prompt="": (order.append("asked"), "n")[1])
    rc = cli.main(
        ["-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/foo-1.0", 3, "hint")]),
        protect_fn=lambda run, plan: (order.append("protect"),
                                      Protection(run_id=run.run_id, archive_dir="/tmp/x"))[1],
        cleanup_fn=lambda prot: (order.append("cleanup"), ["cleaned"])[1],
    )
    assert rc == 0  # user denied the merge
    assert order == ["protect", "asked", "cleanup"]  # point existed, then denied, then removed
    assert calls() == [["app-misc/foo", "--pretend"]]  # merge never started


def test_protection_failure_noninteractive_refuses(emerge_stub, ok_compat, tmp_path):
    binary, calls = emerge_stub
    failed = Protection(run_id="x", failed=True)
    rc = cli.main(
        ["--noninteractive", "-a", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: failed,
    )
    assert rc == 5
    assert calls() == [["sys-libs/glibc", "--pretend"]]


def test_resume_reuses_existing_recovery_point(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub

    def input_y(prompt=""):
        return "y"

    import builtins as b
    b_input = b.input
    try:
        b.input = input_y
        run = state.new_run(["--resume", "-a", "sys-apps/x"], Mode())
        run.state = state.INCIDENT
        run.protection = {"snapshot": "/snap/keep", "archive": None, "failed": False}
        state.save_run(run, runs_dir=tmp_path)

        def boom(run, plan):
            raise AssertionError("protect must not re-run when recovery point exists")

        rc = cli.main(
            ["--resume", "-a", "sys-apps/x"],
            emerge_binary=binary,
            runs_dir=str(tmp_path),
            plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-editors/vim-9.1", 5, "hint")]),
            protect_fn=boom,
            cleanup_fn=lambda p: [],
        )
    finally:
        b.input = b_input
    assert rc == 0
    assert "reusing recovery point" in capsys.readouterr().err
    assert calls() == [["sys-apps/x", "--pretend"], ["sys-apps/x"]]


def test_merge_failure_records_incident_context(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    monkeypatch.setenv(
        "EMERGE_STUB_ERR",
        " * ERROR: app-misc/foo-1.2.3::gentoo failed (compile phase):\n"
        " *   emake failed\n",
    )
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    rc = cli.main(
        ["-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.2.3", 5, "hint")]),
        protect_fn=lambda run, plan: Protection(run_id=run.run_id),
    )
    assert rc == 1
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["state"] == "INCIDENT"
    inc = saved["incident"]
    assert inc["class"] == "compile"
    assert inc["cpv"] == "app-misc/foo-1.2.3"
    assert inc["phase"] == "compile"
    assert inc["build_log"] == "/var/tmp/portage/app-misc/foo-1.2.3/temp/build.log"
    assert "emake failed" in inc["stderr_tail"]


def test_incident_consults_agent_and_prints_proposal(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_ERR", "sandbox: write access denied: /usr/share/x")
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"endpoint": "http://localhost:1/v1", "model": "m"}')
    seen = []

    def fake_agent(inc):
        seen.append(inc)
        return "PROPOSAL: add sandbox manifest"

    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        config_path=str(cfg),
        plan_fn=lambda a, s: None,
        protect_fn=lambda run, plan: Protection(run_id=run.run_id),
        agent_fn=fake_agent,
    )
    assert rc == 1
    assert seen and seen[0]["class"] == "sandbox"
    err = capsys.readouterr().err
    assert "consulting agent" in err and "PROPOSAL: add sandbox manifest" in err
    assert "\x1b" not in err


def test_agent_proposal_tty_gets_two_colors(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_ERR", "sandbox: write access denied: /usr/share/x")
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"endpoint": "http://localhost:1/v1", "model": "m"}')

    class TTY(io.StringIO):
        def isatty(self):
            return True

    tty = TTY()
    monkeypatch.setattr(cli.sys, "stderr", tty)
    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        config_path=str(cfg),
        plan_fn=lambda a, s: None,
        protect_fn=lambda run, plan: Protection(run_id=run.run_id),
        agent_fn=lambda inc: "PROPOSAL: relink\nQUESTION: which slot?",
    )
    assert rc == 1
    err = tty.getvalue()
    assert "\x1b[36mPROPOSAL: relink\x1b[0m" in err
    assert "\x1b[33mQUESTION: which slot?\x1b[0m" in err


def test_post_run_digest_on_success(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"show_digest": true}')
    rc = cli.main(["app-misc/foo"], str(binary), config_path=str(cfg),
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    err = capsys.readouterr().err
    assert "run digest:" in err
    assert "STUB-OK" in err or "built/installed" in err


def test_post_run_digest_off(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"show_digest": false}')
    rc = cli.main(["app-misc/foo"], str(binary), config_path=str(cfg),
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    assert "run digest:" not in capsys.readouterr().err


def test_changelog_mode_local_news_only(tmp_path, capsys):
    news = tmp_path / "news"
    news.mkdir()
    (news / "2026-01-01-openssl.news").write_text("Title: OpenSSL upgrade needed\nDo things.\n")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"news_dir": str(news), "gh_repos": [], "git_urls": []}))
    rc = cli.main(["--changelog"], "emerge", config_path=str(cfg), runs_dir=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "OpenSSL upgrade needed" in out


def test_status_messages_plain_under_capturing(emerge_stub, ok_compat, tmp_path, capsys):
    binary, _ = emerge_stub
    rc = cli.main(
        ["--resume"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "no incomplete emerge-ai run" in err and "\x1b" not in err


def test_agent_error_red_on_tty_stderr(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, _ = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_ERR", "sandbox: write access denied: /usr/share/x")
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")

    class TTY(io.StringIO):
        def isatty(self):
            return True

    tty = TTY()
    monkeypatch.setattr(cli.sys, "stderr", tty)
    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        config_path=str(cfg),
        plan_fn=lambda a, s: None,
        protect_fn=lambda run, plan: Protection(run_id=run.run_id),
    )
    assert rc == 1
    err = tty.getvalue()
    assert "\x1b[31memerge-ai: no LLM endpoint configured" in err
    assert "\x1b[0m" in err


# --- e2e: interactive operator question on a failing plan (spec: agent-loop-consent) ---

ASK_QUESTION = {
    "question": "Which init do you run?",
    "options": [
        {"label": "systemd", "consequences": "rebuilds 40 packages"},
        {"label": "openrc", "consequences": "keeps the queue"},
    ],
}


class AskWhenOfferedClient:
    """Scripted model for the agent path: it asks the operator only when the
    ask_operator tool was handed to it, otherwise it concludes with assumptions."""

    def __init__(self, cfg=None, **kwargs):
        self.system = ""
        self.tools: list[str] = []
        self.chats = 0

    def chat(self, messages, tools=None, temperature=0.2):
        from emerge_ai.llm import Response, ToolCall

        self.tools = [t["function"]["name"] for t in (tools or [])]
        if not self.chats:
            self.system = messages[0]["content"]
        self.chats += 1
        answers = [m for m in messages if m.get("role") == "tool"]
        if answers:
            payload = json.loads(answers[-1]["content"])
            chosen = payload.get("choice") or payload.get("free_text") or "nothing"
            return Response(content=f"PROPOSAL: go ahead, {chosen}")
        if "ask_operator" in self.tools:
            return Response(content="", tool_calls=[
                ToolCall(id="q1", name="ask_operator", arguments=ASK_QUESTION)
            ])
        return Response(content="PROPOSAL: pin the slot\nASSUMPTIONS: openrc, no rebuild")

    def render(self, resp, stream=None):
        if resp.content:
            print(resp.content, file=stream)


@pytest.fixture
def agent_path(monkeypatch, tmp_path):
    """Real IncidentAgent on a scripted client, no portage/rules lookup, failing plan."""
    from emerge_ai import prompts

    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "core.md").write_text("Be terse.")
    monkeypatch.setenv("EMERGE_AI_PROMPTS_DIR", str(rules))
    monkeypatch.setattr(cli.portage_compat, "emerge_info", lambda: "")
    scripted = AskWhenOfferedClient()
    monkeypatch.setattr(cli, "LLMClient", lambda cfg, **kw: scripted)
    (tmp_path / "emerge-ai.json").write_text('{"endpoint": "http://127.0.0.1:9/v1"}')
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_ERR", "slot conflict: dev-util/glslang")
    return scripted


class _TTYStdin:
    def isatty(self) -> bool:
        return True


def test_e2e_interactive_question_answers_flow_into_proposal(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())
    prompts: list = []

    def _input(prompt=""):
        prompts.append(prompt)
        return "2"

    monkeypatch.setattr(builtins, "input", _input)
    rc = cli.main(
        ["-a", "sys-apps/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: None,
    )
    assert rc == 1  # the plan failure code is not masked by the dialogue
    assert calls() == [["sys-apps/foo", "--pretend"]]  # nothing was merged
    err = capsys.readouterr().err
    assert "Which init do you run?" in err
    assert "  2. openrc — keeps the queue" in err
    assert "> openrc — keeps the queue" in err  # the answer is echoed
    assert "PROPOSAL: go ahead, openrc — keeps the queue" in err  # answer reached the model
    assert "ask_operator" in agent_path.tools


def test_e2e_interactive_free_text_and_quit_stay_in_stderr(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_path, capsys):
    binary, _ = emerge_stub
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())
    monkeypatch.setattr(builtins, "input", lambda prompt="": "keep the old slot")
    rc = cli.main(["-a", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None)
    assert rc == 1
    err = capsys.readouterr().err
    assert "PROPOSAL: go ahead, keep the old slot" in err
    out = capsys.readouterr().out
    assert "Which init" not in out  # the dialogue never leaks to stdout


def test_e2e_pretend_neither_asks_nor_reads_stdin(emerge_stub, ok_compat, monkeypatch, tmp_path, agent_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")  # -p never spells --pretend, so fail the plain rc
    monkeypatch.setattr(cli.sys, "stdin", _TTYStdin())  # a TTY must not enable questions under -p

    def _boom(prompt=""):
        raise AssertionError("stdin must stay untouched in --pretend")

    monkeypatch.setattr(builtins, "input", _boom)
    rc = cli.main(["-p", "sys-apps/foo"], emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: None)
    assert rc == 1
    assert "ask_operator" not in agent_path.tools
    assert "Do not ask the operator" in agent_path.system
    assert "QUESTION:" not in agent_path.system
    err = capsys.readouterr().err
    assert "ASSUMPTIONS: openrc, no rebuild" in err
    assert "choose, [c] own text" not in err


def test_plan_phase_llm_summary_with_endpoint(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"endpoint": "http://localhost:1/v1", "model": "m"}')
    seen = []

    class FakeClient:
        def __init__(self, cfg, show_reasoning=False):
            pass

        def chat(self, messages):
            seen.append(messages)
            return type("R", (), {"content": "watch the tier-1 rebuild"})()

    monkeypatch.setattr(cli, "LLMClient", FakeClient)
    plan = Plan(entries=[PlanEntry("app-misc/foo-1.0", 1, "hint")])
    rc = cli.main(["-p", "app-misc/foo"], str(binary), config_path=str(cfg),
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: plan)
    assert rc == 0
    out = capsys.readouterr().out
    assert "llm summary:" in out and "watch the tier-1 rebuild" in out
    assert len(seen) == 1 and "plan briefer" in seen[0][0]["content"]


def test_plan_phase_no_llm_summary_without_endpoint(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")

    def no_client(cfg, show_reasoning=False):
        raise AssertionError("LLMClient must not be built without endpoint")

    monkeypatch.setattr(cli, "LLMClient", no_client)
    plan = Plan(entries=[PlanEntry("app-misc/foo-1.0", 1, "hint")])
    rc = cli.main(["-p", "app-misc/foo"], str(binary), config_path=str(cfg),
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: plan)
    assert rc == 0
    out = capsys.readouterr().out
    assert "plan digest:" in out and "llm summary:" not in out


def _changelog_cfg(tmp_path, **extra):
    news = tmp_path / "news"
    news.mkdir(exist_ok=True)
    (news / "2026-01-01-openssl.news").write_text("Title: OpenSSL upgrade needed\nDo things.\n")
    cfg = tmp_path / "cfg.json"
    data = {"show_digest": False, "news_dir": str(news), "gh_repos": [], "git_urls": []}
    data.update(extra)
    cfg.write_text(json.dumps(data))
    return cfg


def test_post_run_changelog_off_by_default(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = _changelog_cfg(tmp_path)

    def no_call(*a, **k):
        raise AssertionError("collect_digest must not run when changelog_digest is off")

    monkeypatch.setattr(cli.changelog, "collect_digest", no_call)
    rc = cli.main(["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"], str(binary), config_path=str(cfg), runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    assert rc == 0
    assert "changelog digest" not in capsys.readouterr().err


def test_post_run_changelog_on_saves_report(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = _changelog_cfg(tmp_path, changelog_digest=True, endpoint="http://localhost:1/v1")
    runs = tmp_path / "runs"
    runs.mkdir()

    class FakeClient:
        def __init__(self, cfg, show_reasoning=False):
            pass

        def chat(self, messages):
            assert "Merged in this run: app-misc/foo-1.0" in messages[1]["content"]
            return type("R", (), {"content": "- OpenSSL upgrade needed"})()

    monkeypatch.setattr(cli, "LLMClient", FakeClient)
    rc = cli.main(["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"], str(binary), config_path=str(cfg), runs_dir=str(runs),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    assert rc == 0
    err = capsys.readouterr().err
    assert "emerge-ai changelog digest:" in err and "OpenSSL upgrade needed" in err
    assert state.latest_incomplete(runs_dir=runs) is None  # run completed; report saved anyway
    saved = [state.load_run(p.stem, runs_dir=runs) for p in runs.glob("*.json")]
    assert any(r.changelog and "OpenSSL" in r.changelog for r in saved)


def test_post_run_changelog_without_endpoint_is_raw(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = _changelog_cfg(tmp_path, changelog_digest=True)

    def no_client(cfg, show_reasoning=False):
        raise AssertionError("no LLMClient without endpoint")

    monkeypatch.setattr(cli, "LLMClient", no_client)
    rc = cli.main(["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"], str(binary), config_path=str(cfg), runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    assert rc == 0
    err = capsys.readouterr().err
    assert "changelog digest (raw):" in err and "OpenSSL upgrade needed" in err


def test_post_run_changelog_failure_keeps_rc(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = _changelog_cfg(tmp_path, changelog_digest=True)

    def boom(*a, **k):
        raise RuntimeError("source exploded")

    monkeypatch.setattr(cli.changelog, "collect_digest", boom)
    rc = cli.main(["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"], str(binary), config_path=str(cfg), runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    assert rc == 0
    assert "changelog digest skipped: source exploded" in capsys.readouterr().err


def test_post_run_changelog_not_called_on_failure(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    cfg = _changelog_cfg(tmp_path, changelog_digest=True)

    def no_call(*a, **k):
        raise AssertionError("no changelog digest for a failed run")

    monkeypatch.setattr(cli.changelog, "collect_digest", no_call)
    rc = cli.main(["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"], str(binary), config_path=str(cfg), runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    assert rc == 1


def test_ask_pretend_records_plan_and_never_merges(emerge_stub, ok_compat, monkeypatch, tmp_path, capsys):
    """cli-compat «Связка -a -p не устанавливает»: план сохраняется, merge нет."""
    import builtins

    from emerge_ai.plan import Plan, PlanEntry

    binary, calls = emerge_stub
    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("stdin read"))
    runs = tmp_path / "runs"
    runs.mkdir()
    plan = Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")])
    rc = cli.main(["-a", "-p", "app-misc/foo"], str(binary), config_path=str(_changelog_cfg(tmp_path)),
                  runs_dir=str(runs), plan_fn=lambda a, s: plan)
    assert rc == 0
    assert calls() == [["-p", "app-misc/foo"]]  # single resolve, no merge run
    out = capsys.readouterr()
    assert "Proceed?" not in out.err and "emerge-ai plan digest:" in out.out
    saved = [state.load_run(p.stem, runs_dir=runs) for p in runs.glob("*.json")]
    assert any(r.plan and r.plan[0]["cpv"] == "app-misc/foo-1.0" for r in saved)


def test_ask_pretend_plan_failure_persists_incident(emerge_stub, ok_compat, monkeypatch, tmp_path):
    """cli-compat «Кластер -ap»/провал плана: incident plan-failed, rc передан."""
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "7")
    runs = tmp_path / "runs"
    runs.mkdir()
    rc = cli.main(["-ap", "app-misc/foo"], str(binary), config_path=str(_changelog_cfg(tmp_path)),
                  runs_dir=str(runs), plan_fn=lambda a, s: None)
    assert rc == 7
    assert calls() == [["-p", "app-misc/foo"]]  # no second (merge) run
    saved = [state.load_run(p.stem, runs_dir=runs) for p in runs.glob("*.json")]
    assert any(r.incident and r.incident["class"] == "plan-failed" for r in saved)


def test_plain_protect_before_merge_tier1(emerge_stub, ok_compat, monkeypatch, tmp_path):
    """system-rollback: обычный запуск защищает tier<=4 до merge, без вопросов."""
    binary, calls = emerge_stub
    import builtins

    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("stdin read"))
    order = []
    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: (order.append("protect"),
                                      Protection(run_id=run.run_id, archive_dir="/tmp/a"))[1],
        cleanup_fn=lambda prot: ["dropped"],
    )
    assert rc == 0
    assert order == ["protect"]  # point created, merge went ahead, cleanup after success
    assert calls() == [["sys-libs/glibc", "--pretend"], ["sys-libs/glibc"]]


def test_noninteractive_tier1_blocked_before_mutations(emerge_stub, ok_compat, tmp_path):
    """wire-autonomy-gate: plain неинтерактив tier 1 — остановка до мутаций, rc 7,
    точка защищённости вычищена, решение в аудите."""
    binary, calls = emerge_stub
    audit = tmp_path / "decisions.log"
    order = []
    rc = cli.main(
        ["--noninteractive", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        audit_path=str(audit),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: (order.append("protect"),
                                      Protection(run_id=run.run_id, archive_dir="/tmp/a"))[1],
        cleanup_fn=lambda prot: (order.append("cleanup"), ["dropped"])[1],
    )
    assert rc == 7  # не код emerge — отдельный код отказа гейта
    assert calls() == [["sys-libs/glibc", "--pretend"]]  # merge не стартовал
    assert order == ["protect", "cleanup"]  # created point dropped on refusal
    import json

    line = json.loads(audit.read_text().splitlines()[-1])
    assert line["decision"] == "denied" and line["tiers"] == [1]


def test_plain_rest_tier_skips_protect(emerge_stub, ok_compat, tmp_path):
    binary, calls = emerge_stub
    called = []
    rc = cli.main(
        ["--noninteractive", "app-editors/vim"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-editors/vim-9.1", 5, "hint")]),
        protect_fn=lambda run, plan: called.append(1),
    )
    assert rc == 0
    assert called == []  # rest-tier-only queue: no recovery point at all
    assert len(calls()) == 2


def test_plain_plan_fn_crash_protects_unconditionally(emerge_stub, ok_compat, tmp_path, capsys):
    """D4: тиры недоступны -> точка запрошена безусловно; сбой точки -> rc 5 (noninteractive)."""
    binary, calls = emerge_stub

    def crash(args, tiers):
        raise RuntimeError("resolver exploded")

    called = []
    failed = Protection(run_id="x", failed=True)
    rc = cli.main(
        ["--noninteractive", "sys-apps/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=crash,
        protect_fn=lambda run, plan: (called.append(plan), failed)[1],
    )
    assert rc == 5
    assert called == [None]  # protect demanded despite the missing plan
    assert calls() == [["sys-apps/foo", "--pretend"]]  # merge blocked
    err = capsys.readouterr().err
    assert "plan enrichment skipped" in err
    assert "unresolvable queue" in err


def test_resume_rerun_plan_failure_keeps_incident_state(emerge_stub, ok_compat, monkeypatch, tmp_path):
    """Повторный провал плана на уже INCIDENT-ране: без IllegalTransition-краша."""
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "3")
    run = state.new_run(["sys-apps/foo"], Mode(noninteractive=True))
    run.state = state.INCIDENT
    run.incident = {"class": "block"}
    state.save_run(run, runs_dir=tmp_path)

    rc = cli.main(
        ["--noninteractive", "--resume"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: pytest.fail("plan_fn must not run after plan resolve failed"),
    )
    assert rc == 3
    assert calls() == [["--pretend"]]  # plan resolve failed; merge never ran
    after = json.loads((tmp_path / f"{run.run_id}.json").read_text())
    assert after["state"] == "INCIDENT"
    assert after["incident"]["class"] == "plan-failed"


def test_alias_risk_flag_full_auto_merge(emerge_stub, ok_compat, tmp_path):
    """e2e: --noninteractive --i-understand-the-risks -a автономен; emerge флага не видел."""
    binary, calls = emerge_stub
    rc = cli.main(
        ["--noninteractive", "--i-understand-the-risks", "-a", "app-misc/foo"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 1, "hint")]),
    )
    assert rc == 0
    assert calls() == [["app-misc/foo", "--pretend"], ["app-misc/foo"]]
    assert all("--i-understand" not in arg for call in calls() for arg in call)


def _failing_stub_env(monkeypatch):
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")


def test_merge_failure_tier1_tty_offer_restores(emerge_stub, ok_compat, monkeypatch, tmp_path):
    """system-rollback: сбой tier≤4 с точкой + TTY-согласие → откат исполнен, задокументирован."""
    binary, calls = emerge_stub
    _failing_stub_env(monkeypatch)
    monkeypatch.setattr(builtins, "input", lambda p="": "y")
    prot = Protection(run_id="x", archive_dir="/tmp/point")
    seen = []
    rc = cli.main(
        ["sys-apps/critical"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-apps/critical-1.0", 1, "hint")]),
        protect_fn=lambda run, plan: prot,
        rollback_executor=lambda p: seen.append(p.archive_dir),
    )
    assert rc == 1  # код emerge сохраняется
    assert seen == ["/tmp/point"]
    run = next(tmp_path.glob("*.json"))
    assert json.loads(run.read_text())["rollback"] == "restored"


def test_merge_failure_offer_declined_keeps_artifacts(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    _failing_stub_env(monkeypatch)
    monkeypatch.setattr(builtins, "input", lambda p="": "n")
    cleaned = []
    restored = []
    rc = cli.main(
        ["sys-apps/critical"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-apps/critical-1.0", 1, "hint")]),
        protect_fn=lambda run, plan: Protection(run_id="x", archive_dir="/tmp/point"),
        cleanup_fn=lambda p: cleaned.append(1) or [],
        rollback_executor=lambda p: restored.append(1),
    )
    assert rc == 1
    assert restored == [] and cleaned == []  # отказ: ничего не восстановлено, артефакты целы


def test_merge_failure_noninteractive_hints_without_restoring():
    """Seam-тест: noninteractive без флага — только подсказка, артефакты целы.
    (Через main этот случай недостижим: гейт автономности не пустит tier≤4 merge.)"""
    from emerge_ai.cli import _offer_rollback
    from emerge_ai.flags import Mode
    from emerge_ai.state import RunState

    restored = []
    run = RunState(run_id="r")
    _offer_rollback(
        Mode(noninteractive=True),
        Protection(run_id="x", archive_dir="/tmp/point"),
        run,
        executor=lambda p: restored.append(1),
    )
    assert restored == [] and run.rollback == "offered-skipped"


def test_merge_failure_rest_tier_has_no_offer(emerge_stub, ok_compat, monkeypatch, tmp_path):
    binary, calls = emerge_stub
    _failing_stub_env(monkeypatch)
    monkeypatch.setattr(builtins, "input", lambda p="": pytest.fail("must not ask"))
    called = []
    rc = cli.main(
        ["sys-apps/relax"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
        rollback_fn=lambda *a, **k: called.append(1),
    )
    assert rc == 1 and called == []  # rest-tier: точки нет — предложения нет


# --- wire-agent-apply-loop: repair ladder (H5) ---

REPAIR_STUB = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("EMERGE_STUB_LOG")
if log:
    with open(log, "a") as f:
        f.write(" ".join(sys.argv[1:])
                + " |ACCEPT_KEYWORDS=" + os.environ.get("ACCEPT_KEYWORDS", "") + "\\n")
print("STUB-OUT line1")
if "--pretend" in sys.argv or "-p" in sys.argv:
    sys.exit(0)
marker = os.environ.get("EMERGE_STUB_MARKER")
if marker and os.path.exists(marker):
    sys.exit(0)
err = os.environ.get("EMERGE_STUB_ERR")
if err:
    print(err, file=sys.stderr)
if marker:
    open(marker, "w").close()
sys.exit(1)
"""


@pytest.fixture
def repair_stub(tmp_path, monkeypatch):
    """pretend всегда успешен; merge падает один раз (первый повтор проходит),
    и пишет ACCEPT_KEYWORDS из окружения в лог вызовов."""
    path = tmp_path / "emerge"
    path.write_text(REPAIR_STUB)
    path.chmod(path.stat().st_mode | 0o111)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("EMERGE_STUB_LOG", str(log))
    marker = tmp_path / "failed-once"
    monkeypatch.setenv("EMERGE_STUB_MARKER", str(marker))

    def calls() -> list[list[str]]:
        if not log.exists():
            return []
        return [line.split() for line in log.read_text().splitlines()]

    return str(path), calls


def _repair_agent(monkeypatch, tmp_path):
    """Endpoint + скриптованный клиент + правила: _maybe_agent даёт proposal."""
    (tmp_path / "emerge-ai.json").write_text(
        '{"endpoint": "http://127.0.0.1:9/v1", "model": "m"}')
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "core.md").write_text("Be terse.")
    monkeypatch.setenv("EMERGE_AI_PROMPTS_DIR", str(rules))
    monkeypatch.setattr(cli.portage_compat, "emerge_info", lambda: "")

    class ProposalClient:
        def __init__(self, cfg, show_reasoning=False):
            pass

        def chat(self, messages, tools=None, temperature=0.2):
            from emerge_ai.llm import Response
            return Response(content="PROPOSAL: a plain retry should clear it")

        def render(self, resp, stream=None):
            if resp.content:
                print(resp.content, file=stream or sys.stdout)

    scripted = ProposalClient(None)
    monkeypatch.setattr(cli, "LLMClient", lambda cfg, **kw: scripted)


def _run_states(tmp_path) -> list[dict]:
    return [json.loads(f.read_text())
            for f in tmp_path.glob("*.json") if f.name != "cfg.json"]


def test_repair_matrix_responsibility_applies_retry(repair_stub, ok_compat, monkeypatch,
                                                    tmp_path, capsys):
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging app-misc/foo-1.0")
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    out, err = capsys.readouterr()
    assert rc == 0  # retry починил: прогон завершён успехом
    assert "applied repair variant [retry]" in err and "autonomy matrix:" in err
    assert _run_states(tmp_path)[0]["repair"] == [
        {"attempt": 1, "variant": "retry", "retry_rc": 0}]
    assert len(calls()) == 3  # pretend + неудачный merge + повтор


def test_repair_noninteractive_rest_tier_auto_applies(repair_stub, ok_compat, monkeypatch,
                                                      tmp_path, capsys):
    """Сценарий спеки: --noninteractive + rest-tier -> применение без вопроса."""
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging app-misc/foo-1.0")
    monkeypatch.setattr(builtins, "input", lambda p="": pytest.fail("must not ask"))
    rc = cli.main(
        ["sys-apps/thing", "--noninteractive"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    out, err = capsys.readouterr()
    assert rc == 0
    assert "applied repair variant [retry]" in err  # обоснование матрицы печатается всегда
    assert "--noninteractive: rest-tier" in err
    assert len(calls()) == 3


def test_repair_matrix_no_consent_stays_advisory(emerge_stub, ok_compat, monkeypatch,
                                                 tmp_path, capsys):
    """Матрица не даёт AUTO без флага (plan-failed -> tier 1): отказ, код сбоя."""
    binary, calls = emerge_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_ERR", "!!! Unable to resolve --or slot conflict")
    rc = cli.main(["sys-apps/thing"], emerge_binary=binary, runs_dir=str(tmp_path))
    out, err = capsys.readouterr()
    assert rc == 1  # отказ = прежнее консультационное поведение
    assert "auto-repair refused" in err
    assert "PROPOSAL" in err  # предложение осталось в выводе
    assert _run_states(tmp_path)[0]["repair"] == []
    assert len(calls()) == 1  # система не тронута: один resolve


def test_repair_audit_unwritable_fail_closed(repair_stub, ok_compat, monkeypatch,
                                             tmp_path, capsys):
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging")
    monkeypatch.setattr(cli.gate_mod, "audit", lambda *a, **k: False)
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    out, err = capsys.readouterr()
    assert rc == 1
    assert "decision audit unwritable — fail-closed" in err
    assert _run_states(tmp_path)[0]["repair"] == []
    assert len(calls()) == 2  # без аудита нет ни применения, ни повтора


def test_repair_interactive_gate_applies_choice(repair_stub, ok_compat, monkeypatch,
                                                tmp_path, capsys):
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging")
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
        input_fn=lambda prompt="": "1", confirm_fn=lambda prompt="": True,
    )
    out, err = capsys.readouterr()
    assert rc == 0
    assert "applied repair variant [retry]" in err
    assert _run_states(tmp_path)[0]["repair"] == [
        {"attempt": 1, "variant": "retry", "retry_rc": 0}]


def test_repair_interactive_refusal_keeps_exit_code(repair_stub, ok_compat, monkeypatch,
                                                    tmp_path, capsys):
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging")
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
        input_fn=lambda prompt="": "q", confirm_fn=lambda prompt="": pytest.fail("no ask"),
    )
    out, err = capsys.readouterr()
    assert rc == 1  # код последнего сбоя emerge
    assert "consent gate: quit — system untouched" in err
    assert _run_states(tmp_path)[0]["repair"] == []
    assert len(calls()) == 2


def test_repair_limit_two_cycles_then_report(emerge_stub, ok_compat, monkeypatch,
                                             tmp_path, capsys):
    binary, calls = emerge_stub
    _repair_agent(monkeypatch, tmp_path)
    _failing_stub_env(monkeypatch)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging")
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    out, err = capsys.readouterr()
    assert rc == 1
    assert "repair limit (2 apply->retry cycles) reached" in err
    repair = _run_states(tmp_path)[0]["repair"]
    assert [r["variant"] for r in repair] == ["retry", "retry"]
    assert all(r["retry_rc"] == 1 for r in repair)
    assert len(calls()) == 4  # pretend + merge + 2 повтора, третий цикл не начат


def test_repair_without_agent_no_gate_offer(emerge_stub, ok_compat, monkeypatch,
                                            tmp_path, capsys):
    """Нет endpoint'а — циклы починки не включаются вовсе (advisory floor)."""
    binary, calls = emerge_stub
    _failing_stub_env(monkeypatch)
    monkeypatch.setenv("EMERGE_STUB_ERR", "io-error while merging")
    monkeypatch.setattr(builtins, "input", lambda p="": pytest.fail("must not ask"))
    rc = cli.main(["sys-apps/thing", "--noninteractive"],
                  emerge_binary=binary, runs_dir=str(tmp_path),
                  plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]))
    out, err = capsys.readouterr()
    assert rc == 1
    assert "consulting agent" not in err and "consent gate" not in err


def test_repair_env_retry_variant_passes_environment(repair_stub, ok_compat, monkeypatch,
                                                     tmp_path, capsys):
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setenv("EMERGE_STUB_ERR", "These packages are not keyworded: app-misc/foo-1.0")
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    out, err = capsys.readouterr()
    assert rc == 0
    assert "applied repair variant [env-accept-keywords]" in err  # most specific AUTO
    log_lines = [l for l in (c[-1] for c in calls()) if l.startswith("|ACCEPT_KEYWORDS=")]
    # pretend, merge (без env), merge с env — только повтор несёт ACCEPT_KEYWORDS
    assert log_lines == ["|ACCEPT_KEYWORDS=", "|ACCEPT_KEYWORDS=", "|ACCEPT_KEYWORDS=~amd64"]


def test_apply_action_package_edit_idempotent(tmp_path, capsys):
    etc = tmp_path / "etc"
    etc.mkdir()
    run = state.RunState(run_id="r1", argv=[])
    action = {"type": "package-edit", "kind": "unmask",
              "lines": ["app-misc/foo"], "reason": "repair"}
    cli._apply_action(action, run=run, etc_dir=str(etc))
    cli._apply_action(action, run=run, etc_dir=str(etc))
    out, err = capsys.readouterr()
    assert "already present — skipped" in err
    lines = (etc / "package.unmask").read_text().splitlines()
    assert sum(1 for ln in lines if ln.split()[:1] == ["app-misc/foo"]) == 1


def test_apply_action_unknown_type_fail_closed(tmp_path):
    run = state.RunState(run_id="r1", argv=[])
    with pytest.raises(ValueError, match="unknown repair action"):
        cli._apply_action({"type": "curl-pipe-bash"}, run=run, etc_dir=str(tmp_path))


def test_typed_variants_whitelist_by_class():
    from emerge_ai.agent import typed_variants

    plain = typed_variants({"class": "unknown", "argv": ["=sys-apps/x-1"]}, arch="amd64")
    assert [v["key"] for v in plain] == ["retry"]
    masked = typed_variants({"class": "mask", "argv": ["app-misc/foo"]}, arch="amd64")
    assert [v["key"] for v in masked] == ["retry", "package-unmask"]
    assert masked[1]["action"]["kind"] == "unmask"
    kw = typed_variants({"class": "keywords", "argv": []}, arch="amd64")
    assert [v["key"] for v in kw] == ["retry", "env-accept-keywords"]
    assert kw[1]["action"]["env"] == {"ACCEPT_KEYWORDS": "~amd64"}
