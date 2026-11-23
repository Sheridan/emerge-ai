"""CLI: own flags, compat gate, passthrough, -a/-p interception, plan enrichment, run states."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import asdict

from emerge_ai import __version__, hooks, portage_compat, state
from emerge_ai.compat import check_version_compat
from emerge_ai.config import Config, ConfigError, load_config
from emerge_ai.doctor import doctor_report, is_mass_update
from emerge_ai.enrich import plan_digest
from emerge_ai.flags import OWN_FLAG_HELP, parse_own_flags
from emerge_ai import changelog, digest, etcupdate
from emerge_ai.incident import build_incident
from emerge_ai.llm import LLMClient, LLMError
from emerge_ai.plan import build_plan
from emerge_ai import rollback as rollback_mod
from emerge_ai.rollback import Protection
from emerge_ai.runner import confirm, drop_flags, run_emerge, run_emerge_capturing
from emerge_ai.tiers import TierService, snapshot_required

PRETEND_FLAGS = ("-p", "--pretend")
ASK_FLAGS = ("-a", "--ask")


def _version_text() -> tuple[str, int]:
    try:
        pv = portage_compat.portage_version()
    except portage_compat.PortageUnavailable as exc:
        return f"emerge-ai {__version__}\nPortage: unavailable ({exc})\n", 3
    return f"emerge-ai {__version__}\nPortage {pv}\n", 0


def _compat_gate() -> int | None:
    try:
        pv = portage_compat.portage_version()
    except portage_compat.PortageUnavailable as exc:
        print(f"emerge-ai: {exc}", file=sys.stderr)
        return 3
    result = check_version_compat(pv, __version__)
    if not result.ok:
        print(f"emerge-ai: {result.message}", file=sys.stderr)
        return 4
    return None


def _make_tier_service(cfg: Config, cache_path=None):
    client = None
    if cfg.endpoint:
        try:
            client = LLMClient(cfg)
        except LLMError as exc:
            print(f"emerge-ai: {exc}; tiers fall back to conservative", file=sys.stderr)
    return TierService(client, cache_path=cache_path)


def _advance_to_merge(run, runs_dir) -> None:
    next_state = {
        state.VERSION_CHECK: state.PLAN,
        state.PLAN: state.PROTECT,
        state.PROTECT: state.MERGE,
        state.INCIDENT: state.MERGE,
        state.CONFIG: state.MERGE,
    }
    while run.state != state.MERGE and run.state in next_state:
        state.transition(run, next_state[run.state], runs_dir)
    if run.state != state.MERGE:
        raise state.IllegalTransition(f"cannot advance {run.state} to MERGE")


def _default_protect(run, plan) -> Protection:
    if plan is None:
        return Protection(run_id=run.run_id, notes=["no plan: recovery point skipped"])
    return rollback_mod.protect(run.run_id, plan, contents_fn=portage_compat.vdb_contents)


def _maybe_agent(run, config_path, agent_fn=None) -> str | None:
    if not run.incident or run.incident.get("class") == "plan-failed":
        return None
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        return
    if not cfg.endpoint:
        return None
    print("emerge-ai: incident -> consulting agent (proposals only, nothing is executed)...",
          file=sys.stderr)
    try:
        if agent_fn is not None:
            proposal = agent_fn(run.incident)
        else:
            from emerge_ai.agent import IncidentAgent
            from emerge_ai.prompts import collect_context

            client = LLMClient(cfg)
            info = portage_compat.emerge_info()
            agent = IncidentAgent(
                client, context=collect_context(info, cfg.language)
            )
            proposal = agent.propose(run.incident).proposal
        print(f"emerge-ai: agent proposal:\n{proposal}", file=sys.stderr)
        return proposal
    except Exception as exc:  # agent must never mask the original failure rc
        print(f"emerge-ai: agent unavailable: {exc}", file=sys.stderr)
        return None


def _etc_flow(run, config_path, confirm_fn, *, llm=True, input_fn=input, client_factory=None) -> None:
    if not run.incident or run.incident.get("class") != "config-protect":
        return
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    paths = etcupdate.detect(run.incident.get("stderr_tail", ""))
    if not paths:
        return
    print("emerge-ai: config-protect detected: " + ", ".join(paths), file=sys.stderr)
    for newp in paths:
        try:
            print(etcupdate.show_diff(newp), file=sys.stderr)
        except OSError as exc:
            print(f"emerge-ai: no diff for {newp}: {exc}", file=sys.stderr)
    if not llm or not cfg.etc_update_llm:
        print("emerge-ai: etc_update_llm off or raw passthrough — showing diffs only, no actions",
              file=sys.stderr)
        return
    if client_factory is None:
        client_factory = LLMClient
    for newp in paths:
        current = etcupdate.original_of(newp)
        if not Path(newp).exists():
            continue
        try:
            web = None
            if cfg.web_access:
                from emerge_ai.sandbox import Sandbox

                def web(path, _sb=Sandbox()):
                    r = _sb.web_fetch("https://wiki.gentoo.org/")
                    return [(r["url"], r["text"])]
            docs = etcupdate.collect_docs(current, web_fetch=web)
            decision = etcupdate.llm_decide(client_factory(cfg), newp, current, docs)
        except Exception as exc:
            print(f"emerge-ai: etc LLM unavailable: {exc}", file=sys.stderr)
            continue
        print(f"emerge-ai: LLM decision: {decision['action']} — {decision.get('reason', '')}",
              file=sys.stderr)
        for c in decision.get("citations", []):
            print(f"emerge-ai:   cite: {c}", file=sys.stderr)
        try:
            ans = input_fn("Apply LLM decision [Y/n/c=override action[:file]]? ").strip()
            decision = etcupdate.parse_override(ans, decision)
        except EOFError:
            decision = {"action": "keep-current", "reason": "no input", "citations": ["prompt-eof"]}
        except ValueError as exc:
            print(f"emerge-ai: bad override ({exc}); keeping current", file=sys.stderr)
            decision = {"action": "keep-current", "reason": "bad override", "citations": ["user"]}
        res = etcupdate.apply_decision(newp, decision, confirm_fn=lambda _p: True)
        print(f"emerge-ai: etc-update applied={res['applied']} action={res['action']}", file=sys.stderr)



def _post_run_digest(run, output, config_path, runs_dir) -> None:
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    if cfg.post_run_digest:
        print(digest.post_run_digest(run, output), file=sys.stderr)


def _changelog_mode(config_path) -> int:
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    client = LLMClient(cfg) if cfg.endpoint else None
    text = changelog.collect_digest(
        gh_repos=cfg.gh_repos, git_urls=cfg.git_urls, news_dir=cfg.news_dir, client=client
    )
    print(text)
    return 0


def main(
    argv: list[str] | None = None,
    emerge_binary: str = "emerge",
    *,
    config_path: str = "/etc/portage/emerge-ai.json",
    runs_dir: str | None = None,
    tiers_cache: str = "/var/lib/emerge-ai/tiers.json",
    plan_fn=build_plan,
    protect_fn=None,
    cleanup_fn=None,
    agent_fn=None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]
    runs_dir = runs_dir or os.environ.get("EMERGE_AI_RUNS_DIR") or state.RUNS_DIR
    tiers_cache = os.environ.get("EMERGE_AI_TIERS_CACHE") or tiers_cache

    if argv and argv[0] in ("--version", "-V"):
        text, code = _version_text()
        print(text, end="")
        return code

    if argv and argv[0] == "--help":
        print(OWN_FLAG_HELP)
        print("Run 'emerge-ai -h' (or any emerge option) for emerge's own help.")
        return 0

    mode, emerge_args = parse_own_flags(argv)

    if mode.changelog:
        return _changelog_mode(config_path)

    blocked = _compat_gate()
    if blocked is not None:
        return blocked

    resuming = "--resume" in emerge_args
    if resuming:
        emerge_args = [a for a in emerge_args if a != "--resume"]
    run = state.latest_incomplete(runs_dir) if resuming else None
    if resuming:
        if run is None:
            print("emerge-ai: --resume: no incomplete emerge-ai run; starting fresh", file=sys.stderr)
            run = state.new_run(emerge_args, mode)
            state.save_run(run, runs_dir)
        else:
            print(
                f"emerge-ai: resuming run {run.run_id} (state {run.state}"
                + (f", incident: {run.incident['class']})" if run.incident else ")"),
                file=sys.stderr,
            )
    else:
        run = state.new_run(emerge_args, mode)
        state.save_run(run, runs_dir)

    pretend = any(a in PRETEND_FLAGS for a in emerge_args)
    ask = any(a in ASK_FLAGS for a in emerge_args)

    if not pretend and not ask:
        _advance_to_merge(run, runs_dir)
        rc, output = run_emerge_capturing(emerge_args, emerge_binary=emerge_binary)
        if rc != 0:
            run.incident = build_incident(rc, output, emerge_args)
        state.transition(run, state.DONE if rc == 0 else state.INCIDENT, runs_dir)
        if rc != 0:
            run.agent_proposal = _maybe_agent(run, config_path, agent_fn)
            _etc_flow(run, config_path, confirm_fn=lambda _p: False, llm=False)
        else:
            _post_run_digest(run, output, config_path, runs_dir)
        state.save_run(run, runs_dir)
        return rc

    if run.state == state.VERSION_CHECK:
        state.transition(run, state.PLAN, runs_dir)
    plan_args = list(emerge_args)
    if ask and not pretend:
        plan_args.append("--pretend")
    rc, output = run_emerge_capturing(plan_args, emerge_binary=emerge_binary)
    if rc != 0:
        run.incident = {"class": "plan-failed", "returncode": rc}
        state.save_run(run, runs_dir)
        return rc

    plan = None
    try:
        cfg = load_config(config_path)
        tier_service = _make_tier_service(cfg, cache_path=tiers_cache)
        plan = plan_fn(emerge_args, tier_service)
        run.plan = [asdict(e) for e in plan.entries]
        state.save_run(run, runs_dir)
        print(plan_digest(plan))
        if is_mass_update(emerge_args, plan):
            for line in doctor_report(plan):
                print(line, file=sys.stderr)
    except Exception as exc:  # enrichment must never break emerge's own flow
        print(f"emerge-ai: plan enrichment skipped: {exc}", file=sys.stderr)

    hooks.run_hook(output, mode)

    if ask:
        if mode.noninteractive:
            if not mode.responsibility:
                print(
                    "emerge-ai: --noninteractive: proceeding (autonomy matrix; "
                    "tier gate re-checked before mutations)",
                    file=sys.stderr,
                )
        elif not confirm():
            print("emerge-ai: aborted by user.", file=sys.stderr)
            state.transition(run, state.DONE, runs_dir)
            return 0
        merge_args = drop_flags(emerge_args, ASK_FLAGS + PRETEND_FLAGS)
        if run.state == state.PLAN:
            state.transition(run, state.PROTECT, runs_dir)
        pfn = protect_fn or _default_protect
        if run.protection:
            prot = Protection(
                run_id=run.run_id,
                snapshot=run.protection.get("snapshot"),
                archive_dir=run.protection.get("archive"),
                notes=["reusing recovery point from earlier attempt"],
            )
        else:
            prot = pfn(run, plan)
        for note in prot.notes:
            print(f"emerge-ai: {note}", file=sys.stderr)
        run.protection = {
            "snapshot": prot.snapshot,
            "archive": prot.archive_dir,
            "failed": prot.failed,
        }
        state.save_run(run, runs_dir)
        if prot.failed and plan is not None and snapshot_required(plan.entries):
            print(
                "emerge-ai: FAILED to create a recovery point for a tier<=4 queue.",
                file=sys.stderr,
            )
            if mode.noninteractive or not confirm(
                "emerge-ai: merge without recovery point is unsafe. Proceed anyway? [y/N] "
            ):
                print("emerge-ai: aborted: no recovery point.", file=sys.stderr)
                state.transition(run, state.DONE, runs_dir)
                return 5
        state.transition(run, state.MERGE, runs_dir)
        rc, output = run_emerge_capturing(merge_args, emerge_binary=emerge_binary)
        if rc != 0:
            run.incident = build_incident(rc, output, merge_args)
        if rc == 0 and (prot.snapshot or prot.archive_dir):
            for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                print(f"emerge-ai: {line}", file=sys.stderr)
        state.transition(run, state.DONE if rc == 0 else state.INCIDENT, runs_dir)
        if rc != 0:
            run.agent_proposal = _maybe_agent(run, config_path, agent_fn)
            _etc_flow(run, config_path, confirm_fn=confirm)
        else:
            _post_run_digest(run, output, config_path, runs_dir)
        state.save_run(run, runs_dir)
        return rc

    state.transition(run, state.DONE, runs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
