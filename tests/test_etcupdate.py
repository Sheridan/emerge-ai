import json
import os
from pathlib import Path

import pytest

from emerge_ai import etcupdate
from emerge_ai.cli import _etc_flow

FIX = Path("tests/fixtures/etc")


def test_decision_schema_demands_plain_reason():
    msgs = etcupdate.build_merge_prompt("new", "cur", [])
    assert "plain text, no markdown" in msgs[1]["content"]

EMERGE_OUT = """ * --- Failed to merge /etc/ssh/sshd_config
 * Please move /var/tmp/... 
 * config protected: '/etc/ssh/sshd_config'
>>> /etc/ssh/._cfg0000_sshd_config
>>> /var/lib/portage/._cfg0001_xyz.conf
"""


class FakeClient:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.2):
        self.calls += 1
        self.messages = messages
        return json.dumps(self.decision)


def test_detect_and_original():
    paths = etcupdate.detect(EMERGE_OUT)
    assert paths == ["/etc/ssh/._cfg0000_sshd_config", "/var/lib/portage/._cfg0001_xyz.conf"]
    assert etcupdate.original_of("/etc/ssh/._cfg0000_sshd_config") == "/etc/ssh/sshd_config"
    assert etcupdate.detect("nothing protected here") == []


def test_show_diff(tmp_path):
    cur = tmp_path / "sshd_config"
    cur.write_text("Port 2222\n")
    new = tmp_path / "._cfg0000_sshd_config"
    new.write_text("Port 2222\nKexAlgorithms x\n")
    diff = etcupdate.show_diff(str(new), str(cur))
    assert "+KexAlgorithms x" in diff and "---" in diff


def test_show_diff_colors_on_tty_plain_on_pipe(tmp_path):
    import io

    class TTY(io.StringIO):
        def isatty(self):
            return True

    cur = tmp_path / "sshd_config"
    cur.write_text("Port 2222\n")
    new = tmp_path / "._cfg0000_sshd_config"
    new.write_text("Port 2222\nKexAlgorithms x\n")
    colored = etcupdate.show_diff(str(new), str(cur), stream=TTY())
    assert "\x1b[32m+KexAlgorithms x\x1b[0m" in colored
    assert any("\x1b[31m" in l for l in colored.splitlines())
    plain = etcupdate.show_diff(str(new), str(cur), stream=io.StringIO())
    assert "\x1b" not in plain and "+KexAlgorithms x" in plain


def test_parse_decision_validation():
    good = {"action": "merge", "reason": "r", "citations": ["doc: x"], "merged_text": "a\n"}
    assert etcupdate.parse_decision("noise " + json.dumps(good) + " noise") == good
    with pytest.raises(ValueError):
        etcupdate.parse_decision("I think we should keep it")
    with pytest.raises(ValueError):
        etcupdate.parse_decision('{"action": "nuke"}')
    with pytest.raises(ValueError):
        etcupdate.parse_decision('{"action": "merge", "reason": "r", "citations": ["d"]}')
    with pytest.raises(ValueError):
        etcupdate.parse_decision('{"action": "take-new", "reason": "r", "citations": []}')


def test_apply_atomic_backup_confirm_override(tmp_path):
    cur = tmp_path / "sshd_config"
    cur.write_text("OLD\n")
    new = tmp_path / "._cfg0000_sshd_config"
    new.write_text("NEW\n")
    d = {"action": "take-new", "reason": "r", "citations": ["doc"]}
    res = etcupdate.apply_decision(str(new), d, confirm_fn=lambda p: False)
    assert res == {"applied": False, "action": "take-new", "declined": True}
    assert cur.read_text() == "OLD\n" and new.exists()
    res = etcupdate.apply_decision(str(new), d, confirm_fn=lambda p: True)
    assert res["applied"] and cur.read_text() == "NEW\n"
    assert (tmp_path / "sshd_config.pre-emerge-ai").read_text() == "OLD\n"
    assert not new.exists()
    assert not list(tmp_path.glob(".emerge-ai-*"))


def test_parse_override():
    llm = {"action": "take-new", "reason": "r", "citations": ["d"]}
    assert etcupdate.parse_override("", llm) is llm
    assert etcupdate.parse_override("n", llm)["action"] == "keep-current"
    assert etcupdate.parse_override("keep-current", llm)["action"] == "keep-current"
    with pytest.raises(ValueError):
        etcupdate.parse_override("rm -rf /", llm)
    with pytest.raises(ValueError):
        etcupdate.parse_override("merge", llm)


def _cfg_dir(tmp_path, llm_flag=True):
    etc = tmp_path / "etc" / "ssh"
    etc.mkdir(parents=True)
    (etc / "sshd_config").write_text("Port 2222\nPermitRootLogin yes\n")
    (etc / "._cfg0000_sshd_config").write_text("Port 22\nKexAlgorithms x\n")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(
        {"endpoint": "http://x/v1", "etc_update_llm": llm_flag, "web_access": False}))
    return cfg, etc


def incident_for(etc):
    out = (f" * config protected: '{etc / 'sshd_config'}'\n>>> {etc / '._cfg0000_sshd_config'}\n")
    return {"class": "config-protect", "stderr_tail": out}


def test_etc_flow_disabled_shows_diff_only(tmp_path, capsys):
    cfg, etc = _cfg_dir(tmp_path, llm_flag=False)
    run = type("R", (), {"incident": incident_for(etc)})()
    _etc_flow(run, str(cfg), client_factory=lambda c, **kw: pytest.fail("no LLM"))
    err = capsys.readouterr().err
    assert "+KexAlgorithms x" in err and "diffs only" in err
    assert (etc / "._cfg0000_sshd_config").exists()


def test_etc_flow_merge_with_citations(tmp_path, capsys):
    cfg, etc = _cfg_dir(tmp_path)
    merged = "Port 2222\nPermitRootLogin yes\nKexAlgorithms x\n"
    client = FakeClient({"action": "merge", "reason": "keep admin port", "citations": [
        "sshd_config.5.txt: PermitRootLogin Specifies a mode"], "merged_text": merged})
    run = type("R", (), {"incident": {"class": "config-protect", "stderr_tail": EMERGE_OUT}})()
    run.incident = incident_for(etc)
    inputs = iter([""])
    _etc_flow(run, str(cfg), llm=True,
              input_fn=lambda p: next(inputs), client_factory=lambda c, **kw: client)
    err = capsys.readouterr().err
    assert "cite: sshd_config.5.txt" in err
    assert (etc / "sshd_config").read_text() == merged
    assert not (etc / "._cfg0000_sshd_config").exists()


def test_etc_flow_user_override(tmp_path, capsys):
    cfg, etc = _cfg_dir(tmp_path)
    user_file = tmp_path / "mine.conf"
    user_file.write_text("MINE\n")
    client = FakeClient({"action": "take-new", "reason": "r", "citations": ["d"]})
    run = type("R", (), {"incident": {"class": "config-protect", "stderr_tail": EMERGE_OUT}})()
    run.incident = incident_for(etc)
    inputs = iter([f"merge {user_file}"])
    _etc_flow(run, str(cfg), llm=True,
              input_fn=lambda p: next(inputs), client_factory=lambda c, **kw: client)
    assert (etc / "sshd_config").read_text() == "MINE\n"


@pytest.mark.integration
def test_etc_live_replay_sshd_fixture():
    from emerge_ai.config import Config
    from emerge_ai.llm import LLMClient

    cfg = Config(
        endpoint=os.environ.get("EMERGE_AI_TEST_ENDPOINT", "http://127.0.0.1:8080/v1"),
        model=os.environ.get("EMERGE_AI_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"),
        api_key=os.environ.get("EMERGE_AI_TEST_API_KEY"),
    )
    docs = [("tests/fixtures/etc/sshd_config.5.txt", (FIX / "sshd_config.5.txt").read_text())]
    last = None
    for _ in range(3):
        try:
            decision = etcupdate.llm_decide(
                LLMClient(cfg),
                str(FIX / "sshd_config.new"), str(FIX / "sshd_config.current"), docs,
            )
            assert decision["action"] in ("merge", "keep-current"), decision
            assert decision["citations"]
            assert any(
                "sshd_config" in c or "PermitRootLogin" in c or "Port" in c
                for c in decision["citations"]
            ), decision
            if decision["action"] == "merge":
                text = decision["merged_text"]
                assert "Port 2222" in text, "admin port customization must survive"
                assert "KexAlgorithms" in text, "new upstream option must be adopted"
            return
        except AssertionError as exc:
            last = exc
    raise last
