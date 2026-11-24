import json

from emerge_ai import cli
from emerge_ai.agent import IncidentAgent
from emerge_ai.journal import finalize, find, fingerprint, normalize_error
from emerge_ai.plan import Plan, PlanEntry
from emerge_ai.sandbox import Sandbox
from test_agent import ScriptedClient, incident
from test_cli_integration import _repair_agent

INC = {
    "class": "compile",
    "cpv": "app-misc/foo-1.0",
    "stderr_tail": "Sat Jan  3 10:00:00 2026 foo.c:31:24: error: undefined reference to `x'\npid=123",
}


def test_fingerprint_stable_across_noise():
    a = "2026-01-03T10:00:00 /var/tmp/portage/app-misc/foo-1.0/temp/build.log foo.c:31: error: undefined reference to `x' 0x7f12 pid=99"
    b = "2026-05-09T22:11:33 /var/tmp/portage/app-misc/foo-1.2/temp/build.log foo.c:88: error: undefined reference to `x' 0x00ab pid=55"
    assert fingerprint(a) == fingerprint(b)
    c = "fatal error: bar.h: No such file or directory line 4"
    assert fingerprint(c) != fingerprint(a)
    assert "<path>" in normalize_error(a)


def test_finalize_records_only_verified_success(tmp_path):
    p = tmp_path / "journal.jsonl"
    assert finalize(run_id="r1", incident=INC, solution="add dep", actions=["emerge -1 x"],
                    verified_by="merge rc=0 rerun", success=False, path=p) is None
    assert find(path=p) == []
    e = finalize(run_id="r1", incident=INC, solution="add dep", actions=["emerge -1 x"],
                 verified_by="merge rc=0 rerun", success=True, path=p)
    assert e["fingerprint"] == fingerprint(INC["stderr_tail"] + "compile")
    hits = find(fingerprint_value=e["fingerprint"], path=p)
    assert len(hits) == 1 and hits[0]["run_id"] == "r1"
    assert find(regex="add dep", path=p)
    assert find(regex="nothing-matches", path=p) == []


def test_agent_uses_successful_precedent(tmp_path):
    p = tmp_path / "journal.jsonl"
    finalize(run_id="r0", incident=INC, solution="pin dev-libs/bar", actions=["package.accept_keywords"],
             verified_by="rerun rc=0", success=True, path=p)
    client = ScriptedClient([])
    agent = IncidentAgent(client, Sandbox(roots=(str(tmp_path),)), rules="R", journal_path=str(p))
    agent.propose({**INC, "class": "compile"})
    user_msg = client.messages[1]["content"]
    assert "SUCCESSFUL PRECEDENT" in user_msg and "pin dev-libs/bar" in user_msg


# --- writing from the apply loop (spec: agent-loop-consent / wire-journal-writer) ---

def _journal_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _repair_main(repair_stub, monkeypatch, tmp_path, err_text="sandbox: Popen is not allowed"):
    """Один и тот же прогон: merge падает с sandbox-инцидентом, retry чинит."""
    binary, calls = repair_stub
    _repair_agent(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.0.82.2")
    monkeypatch.setenv("EMERGE_STUB_ERR", err_text)
    rc = cli.main(
        ["sys-apps/thing", "--i-understand-the-risks"],
        emerge_binary=binary, runs_dir=str(tmp_path),
        plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
    )
    return rc, calls


def test_repaired_run_writes_exactly_one_entry(repair_stub, monkeypatch, tmp_path, capsys):
    """сбой -> применение -> повтор rc=0: ровно одна запись со всеми полями."""
    rc, calls = _repair_main(repair_stub, monkeypatch, tmp_path)
    out, err = capsys.readouterr()
    assert rc == 0 and "applied repair variant [retry]" in err
    lines = _journal_lines(tmp_path / "journal.jsonl")
    assert len(lines) == 1
    entry = lines[0]
    assert entry["success"] is True
    assert entry["solution"] == "repeat the failed emerge unchanged"
    assert entry["actions"] == ["retry"]
    assert "exited rc=0" in entry["verified_by"]
    run_file = next(f for f in (tmp_path).glob("*.json") if f.name != "emerge-ai.json")
    assert entry["run_id"] == run_file.stem
    inc = json.loads(run_file.read_text())["incident"]
    assert entry["class"] == inc["class"] == "sandbox"
    assert entry["fingerprint"] == fingerprint(inc["stderr_tail"] + inc["class"])


def test_unverified_fix_writes_nothing(repair_stub, monkeypatch, tmp_path, capsys):
    """повтор тоже упал (лимит циклов) — верификации нет, журнал пуст."""
    monkeypatch.delenv("EMERGE_STUB_MARKER")  # merge теперь проваливается всегда
    rc, calls = _repair_main(repair_stub, monkeypatch, tmp_path)
    out, err = capsys.readouterr()
    assert rc == 1 and "repair limit" in err
    assert not (tmp_path / "journal.jsonl").exists()


def test_unwritable_journal_keeps_exit_code(repair_stub, monkeypatch, tmp_path, capsys):
    """незаписываемый журнал — предупреждение в stderr, код выхода не меняется."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    monkeypatch.setattr(cli.journal, "JOURNAL_PATH", str(blocked / "journal.jsonl"))
    rc, calls = _repair_main(repair_stub, monkeypatch, tmp_path)
    out, err = capsys.readouterr()
    assert rc == 0 and "journal write failed" in err


def test_missing_or_corrupt_journal_no_precedent(tmp_path):
    """отсутствующий и битый журнал: find не падает, прецедентов нет."""
    gone = tmp_path / "missing.jsonl"
    assert find(path=gone) == []
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not json at all\n{trunc\n")
    assert find(path=corrupt) == []
    client = ScriptedClient([])
    agent = IncidentAgent(
        client, Sandbox(roots=(str(tmp_path),)), rules="R", journal_path=str(corrupt)
    )
    agent.propose(dict(INC))
    assert "SUCCESSFUL PRECEDENT" not in client.messages[1]["content"]
