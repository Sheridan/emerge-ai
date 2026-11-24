import json
import os
from pathlib import Path

import pytest

from emerge_ai import etcupdate
from emerge_ai.cli import _etc_flow

FIX = Path("tests/fixtures/etc")


def test_decision_schema_demands_plain_reason():
    msgs = etcupdate.build_merge_prompt("new", "cur", [], "english")
    assert "plain text, no markdown" in msgs[1]["content"]


def test_merge_prompt_carries_language_directive():
    for lang in ("de", "russian"):
        msgs = etcupdate.build_merge_prompt("n", "c", [], lang)
        assert f"respond in {lang}" in msgs[0]["content"]
        # machine part of the contract stays language-neutral
        assert '"action"' in msgs[1]["content"]

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


def _cfg_dir(tmp_path, llm_flag=True, web_flag=False, language=None):
    etc = tmp_path / "etc" / "ssh"
    etc.mkdir(parents=True)
    (etc / "sshd_config").write_text("Port 2222\nPermitRootLogin yes\n")
    (etc / "._cfg0000_sshd_config").write_text("Port 22\nKexAlgorithms x\n")
    cfg = tmp_path / "cfg.json"
    data = {"endpoint": "http://x/v1", "etc_update_after_build": llm_flag,
            "agent": {"web_access": web_flag}}
    if language:
        data["language"] = language
    cfg.write_text(json.dumps(data))
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


def _package_use_dir(tmp_path):
    pu = tmp_path / "etc" / "portage" / "package.use" / "dev-libs"
    pu.mkdir(parents=True)
    (pu / "foo").write_text("dev-libs/foo static\n")
    (pu / "._cfg0000_foo").write_text("dev-libs/foo\n")
    return pu


def _web_flaky(monkeypatch, result):
    """Patch Sandbox.web_fetch; returns the list of requested URLs."""
    from emerge_ai import sandbox as sandbox_mod

    urls = []

    def fake(self, url):
        urls.append(url)
        return dict(url=url, **result) if "error" not in result else dict(result)

    monkeypatch.setattr(sandbox_mod.Sandbox, "web_fetch", fake)
    return urls


KEEP = {"action": "keep-current", "reason": "r", "citations": ["d"]}


def _isolate_doc_roots(monkeypatch):
    """Local doc scan hits the real host (/usr/share/doc) — empty it so web
    context is the only variable in these tests."""
    from emerge_ai import cli as cli_mod

    real = cli_mod.etcupdate.collect_docs
    monkeypatch.setattr(cli_mod.etcupdate, "collect_docs",
                        lambda p, web_fetch=None: real(p, web_fetch=web_fetch, doc_roots=()))


def test_etc_flow_web_fetch_catalog_and_wiki(tmp_path, capsys, monkeypatch):
    _isolate_doc_roots(monkeypatch)
    cfg, etc = _cfg_dir(tmp_path, web_flag=True)
    pu = _package_use_dir(tmp_path)
    urls = _web_flaky(monkeypatch, {"content": "WEBDOC-TEXT", "truncated": False})
    client = FakeClient(KEEP)
    run = type("R", (), {"incident": {
        "class": "config-protect",
        "stderr_tail": f">>> {etc / '._cfg0000_sshd_config'}\n>>> {pu / '._cfg0000_foo'}\n",
    }})()
    _etc_flow(run, str(cfg), llm=True, input_fn=lambda p: "y",
              client_factory=lambda c, **kw: client)
    err = capsys.readouterr().err
    assert "etc LLM unavailable" not in err
    wiki = next(u for u in urls if "wiki.gentoo.org" in u)
    assert "search=sshd_config" in wiki and "fulltext=1" in wiki
    catalog = next(u for u in urls if "packages.gentoo.org" in u)
    assert catalog.endswith("/packages/dev-libs/foo")
    # fetched content actually reaches the prompt (FakeClient keeps last messages)
    assert "WEBDOC-TEXT" in client.messages[1]["content"]


def test_etc_flow_web_error_leaves_empty_docs(tmp_path, capsys, monkeypatch):
    _isolate_doc_roots(monkeypatch)
    cfg, etc = _cfg_dir(tmp_path, web_flag=True)
    urls = _web_flaky(monkeypatch, {"error": "network down"})
    client = FakeClient(KEEP)
    run = type("R", (), {"incident": incident_for(etc)})()
    _etc_flow(run, str(cfg), llm=True, input_fn=lambda p: "y",
              client_factory=lambda c, **kw: client)
    err = capsys.readouterr().err
    assert urls  # a fetch was attempted
    assert "web docs unavailable" in err and "network down" in err
    assert "etc LLM unavailable" not in err  # the file was NOT silently skipped
    assert client.calls == 1
    assert "(none; prefer keep-current)" in client.messages[1]["content"]


def test_llm_decide_parses_german_reason(tmp_path):
    new = tmp_path / "._cfg0000_sshd_config"
    new.write_text("Port 22\n")
    cur = tmp_path / "sshd_config"
    cur.write_text("Port 2222\n")
    client = FakeClient({"action": "keep-current", "reason": "Belege fehlen", "citations": ["d"]})
    decision = etcupdate.llm_decide(client, str(new), str(cur), [], "de")
    assert decision == {"action": "keep-current", "reason": "Belege fehlen", "citations": ["d"]}
    assert "respond in de" in client.messages[0]["content"]


def test_etc_flow_language_reaches_llm(tmp_path, capsys):
    cfg, etc = _cfg_dir(tmp_path, language="de")
    client = FakeClient({"action": "keep-current", "reason": "Keine Belege", "citations": ["d"]})
    run = type("R", (), {"incident": incident_for(etc)})()
    _etc_flow(run, str(cfg), llm=True, input_fn=lambda p: "y",
              client_factory=lambda c, **kw: client)
    err = capsys.readouterr().err
    assert "LLM decision: keep-current — Keine Belege" in err
    assert "respond in de" in client.messages[0]["content"]


def test_etc_flow_web_access_off_never_fetches(tmp_path, capsys, monkeypatch):
    cfg, etc = _cfg_dir(tmp_path, web_flag=False)
    from emerge_ai import sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod.Sandbox, "web_fetch",
                        lambda self, url: pytest.fail("must not fetch"))
    client = FakeClient(KEEP)
    run = type("R", (), {"incident": incident_for(etc)})()
    _etc_flow(run, str(cfg), llm=True, input_fn=lambda p: "y",
              client_factory=lambda c, **kw: client)
    assert client.calls == 1  # decision made without any web context


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
                cfg.resolved_language(),
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
