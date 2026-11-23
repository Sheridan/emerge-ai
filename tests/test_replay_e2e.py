"""14.1 end-to-end replay on the stand: stubbed `emerge -uDN @world` with a
blocks failure -> plan+tiers(strata)+doctor -> incident -> agent(strata) ->
gate consent -> verified pretend -> journal. Modules under real LLM only here."""

import json
import os
from pathlib import Path

import pytest

from emerge_ai import cli, gate, journal, state
from emerge_ai.plan import Plan, PlanEntry
from emerge_ai.rollback import Protection

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
        "endpoint": os.environ.get("EMERGE_AI_TEST_ENDPOINT", "http://127.0.0.1:8080/v1"),
        "model": os.environ.get("EMERGE_AI_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"),
        "post_run_digest": False,
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
