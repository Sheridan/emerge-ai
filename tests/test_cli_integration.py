import builtins
import json

import pytest

from emerge_ai import cli, state
from emerge_ai.plan import Plan, PlanEntry


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
    assert calls() == [["--resume"]]
