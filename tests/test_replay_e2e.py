"""14.1 end-to-end replay on the stand: stubbed `emerge -uDN @world` with a
blocks failure -> plan+tiers(strata)+doctor -> incident -> agent(strata) ->
gate consent -> verified pretend -> journal. Modules under real LLM only here."""

import json
import os
from pathlib import Path

import pytest

from aimerge import cli, gate, journal, state
from aimerge.plan import Plan, PlanEntry
from aimerge.rollback import Protection

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _captured_output_is_always_plain(capsys):
    yield
    out, err = capsys.readouterr()
    assert "\x1b" not in out and "\x1b" not in err, "capsys output must never carry ANSI codes"

BLOCKS = Path("tests/fixtures/blocks.txt").read_text()


@pytest.fixture
def ok_compat(monkeypatch):
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.0.82.2")


@pytest.fixture
def e2e_env(tmp_path, emerge_stub, ok_compat, monkeypatch):
    binary, calls = emerge_stub
    monkeypatch.setenv("EMERGE_STUB_RC", "1")
    monkeypatch.setenv("EMERGE_STUB_ERR", BLOCKS)
    monkeypatch.setenv("EMERGE_STUB_PRETEND_RC", "0")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "endpoint": os.environ.get("AIMERGE_TEST_ENDPOINT", "http://127.0.0.1:8080/v1"),
        "model": os.environ.get("AIMERGE_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"),
        "show_digest": False,
    }))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    return binary, calls, cfg, tmp_path


def _plan_fn(args, tier_service):
    nano = tier_service.classify("app-editors/nano")
    glibc = tier_service.classify("sys-libs/glibc")
    return Plan(entries=[
        PlanEntry("app-editors/nano-8.1", nano.tier, nano.reason),
        PlanEntry("sys-libs/glibc-2.42", glibc.tier, glibc.reason),
    ])




def test_replay_world_blocks_end_to_end(e2e_env, capsys):
    binary, calls, cfg, tmp = e2e_env
    rc = cli.main(
        ["--ask", "-uDN", "@world"], binary,
        config_path=str(cfg), runs_dir=str(tmp / "runs"), tiers_cache=str(tmp / "tiers.json"),
        plan_fn=_plan_fn, protect_fn=lambda run, plan=None: Protection(run_id=run.run_id, failed=False),
        cleanup_fn=lambda prot: ["fake cleanup done"],
    )
    err = capsys.readouterr().err
    assert rc != 0

    run_file = next(Path(tmp / "runs").glob("*.json"))
    run = state.load_run(run_file.stem, tmp / "runs")
    assert run.state == state.INCIDENT
    assert run.incident["class"] == "blocks"

    # plan/tiers/doctor happened
    tiers = {e["cpv"].rsplit("-", 1)[0] if "-" in e["cpv"] else e["cpv"]: e["tier"] for e in run.plan}
    nano_tier = [e["tier"] for e in run.plan if "nano" in e["cpv"]][0]
    glibc_tier = [e["tier"] for e in run.plan if "glibc" in e["cpv"]][0]
    assert nano_tier == 5 and glibc_tier <= 2
    assert any("doctor" in l.lower() or "genlop" in l.lower() or "estimate" in l.lower() for l in err.splitlines())

    # agent consulted strata
    assert run.agent_proposal and len(run.agent_proposal) > 30

    # verified pretend -> consent gate -> apply
    verified = cli.run_emerge_capturing(["--pretend", "@world"], emerge_binary=binary)
    assert verified[0] == 0
    actions = []

    def retry():
        os.environ.pop("EMERGE_STUB_RC")
        os.environ.pop("EMERGE_STUB_ERR")
        rc2, _ = cli.run_emerge_capturing(["-uDN", "@world"], emerge_binary=binary)
        actions.append(rc2)

    variants = [
        gate.Variant("retry-after-unblock", "retry world after unblocking atom",
                     pros=["queue unblocked"], risks=["nano tier 5"], tiers=(nano_tier,),
                     kind="fix", action=retry),
    ]
    res = gate.gate(variants, mode={"responsibility": True},
                    confirm_fn=lambda p: pytest.fail("responsibility mode must not prompt"),
                    input_fn=lambda p: "1", audit_path=tmp / "audit.log", echo=lambda *a: None)
    assert res["status"] == "applied" and actions == [0]

    # success -> journal
    entry = journal.finalize(
        run_id=run.run_id, incident=run.incident,
        solution="drop masked atom from world set; re-run", actions=["retry rc=0"],
        verified_by="stub rerun rc=0", success=True, path=tmp / "journal.jsonl",
    )
    hits = journal.find(fingerprint_value=entry["fingerprint"], path=tmp / "journal.jsonl")
    assert len(hits) == 1 and hits[0]["class"] == "blocks" and hits[0]["run_id"] == run.run_id


def test_repair_ladder_journals_then_finds_precedent(repair_stub, ok_compat, monkeypatch,
                                                     tmp_path, capsys):
    """Связочный цикл (agent-loop-consent): фикс петли пишется в журнал самим
    CLI, а повтор того же сбоя доносит прецедент до модели (tmp-путь журнала
    подставляет autouse-фикстура conftest)."""
    binary, calls = repair_stub
    monkeypatch.setenv("EMERGE_STUB_ERR", "sandbox: Popen is not allowed")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "endpoint": os.environ.get("AIMERGE_TEST_ENDPOINT", "http://127.0.0.1:8080/v1"),
        "model": os.environ.get("AIMERGE_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"),
        "show_digest": False,
    }))
    monkeypatch.setattr(cli.portage_compat, "portage_version", lambda: "3.0.82.2")
    monkeypatch.setattr(cli.portage_compat, "emerge_info", lambda: "")

    prompts = []

    class SpyClient:
        """Настоящий strata + запись промптов: прецедент обязан дойти до модели."""

        def __init__(self, cfg_, verbose=False):
            from aimerge.llm import LLMClient
            self._real = LLMClient(cfg_, verbose=verbose)

        def chat(self, messages, tools=None, temperature=0.2):
            prompts.append(list(messages))
            return self._real.chat(messages, tools=tools, temperature=temperature)

        def render(self, resp, stream=None):
            self._real.render(resp, stream=stream)

    monkeypatch.setattr(cli, "LLMClient", lambda cfg_, **kw: SpyClient(cfg_, **kw))

    def run_once():
        return cli.main(
            ["sys-apps/thing", "--i-understand-the-risks"], emerge_binary=binary,
            config_path=str(cfg), runs_dir=str(tmp_path / "runs"),
            plan_fn=lambda a, s: Plan(entries=[PlanEntry("app-misc/foo-1.0", 5, "hint")]),
        )

    assert run_once() == 0  # retry устранил sandbox-сбой
    entries = [json.loads(l) for l in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert len(entries) == 1 and entries[0]["success"] is True
    assert entries[0]["class"] == "sandbox"
    assert "exited rc=0" in entries[0]["verified_by"]

    monkeypatch.setenv("EMERGE_STUB_MARKER", str(tmp_path / "failed-once-2"))  # ещё один сбой
    prompts.clear()
    run_once()
    users = [m["content"] for msgs in prompts for m in msgs if m.get("role") == "user"]
    assert any("SUCCESSFUL PRECEDENT" in c and "repeat the failed emerge unchanged" in c
               for c in users)
