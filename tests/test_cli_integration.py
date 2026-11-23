import builtins
import json

import pytest

from emerge_ai import cli, state
from emerge_ai.plan import Plan, PlanEntry
from emerge_ai.rollback import Protection


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


def test_resume_reuses_incomplete_run_context(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    run = state.new_run(["--resume"], {"noninteractive": True})
    run.state = state.INCIDENT
    run.incident = {"class": "block"}
    state.save_run(run, runs_dir=tmp_path)

    rc = cli.main(
        ["--noninteractive", "--resume"],
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
    assert calls() == [[]]


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
    monkeypatch.setattr(builtins, "input", _iter_input("y", "n"))
    failed = Protection(run_id="x", failed=True)
    rc = cli.main(
        ["-a", "sys-libs/glibc"],
        emerge_binary=binary,
        runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")]),
        protect_fn=lambda run, plan: failed,
    )
    assert rc == 5
    assert calls() == [["-a", "sys-libs/glibc", "--pretend"]]


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
    assert calls() == [["-a", "sys-libs/glibc", "--pretend"]]


def test_resume_reuses_existing_recovery_point(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub

    def input_y(prompt=""):
        return "y"

    import builtins as b
    b_input = b.input
    try:
        b.input = input_y
        run = state.new_run(["--resume", "-a", "sys-apps/x"], {"noninteractive": False})
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
    assert calls() == [["-a", "sys-apps/x", "--pretend"], ["sys-apps/x"]]


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
        ["--noninteractive", "-a", "app-misc/foo"],
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


def test_post_run_digest_on_success(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"post_run_digest": true}')
    rc = cli.main(["app-misc/foo"], str(binary), config_path=str(cfg),
                  runs_dir=str(tmp_path), plan_fn=lambda a, s: None)
    assert rc == 0
    err = capsys.readouterr().err
    assert "run digest:" in err
    assert "STUB-OK" in err or "built/installed" in err


def test_post_run_digest_off(emerge_stub, ok_compat, tmp_path, capsys):
    binary, calls = emerge_stub
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"post_run_digest": false}')
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
