from emerge_ai.agent import IncidentAgent
from emerge_ai.journal import finalize, find, fingerprint, normalize_error
from emerge_ai.sandbox import Sandbox
from test_agent import ScriptedClient, incident

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
