"""CLI: own flags, compat gate, passthrough, -a/-p interception, plan enrichment, run states."""

from __future__ import annotations

import sys
from dataclasses import asdict

from emerge_ai import __version__, hooks, portage_compat, state
from emerge_ai.compat import check_version_compat
from emerge_ai.config import Config, ConfigError, load_config
from emerge_ai.doctor import doctor_report, is_mass_update
from emerge_ai.enrich import plan_digest
from emerge_ai.flags import OWN_FLAG_HELP, parse_own_flags
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


def main(
    argv: list[str] | None = None,
    emerge_binary: str = "emerge",
    *,
    config_path: str = "/etc/portage/emerge-ai.json",
    runs_dir: str = state.RUNS_DIR,
    tiers_cache: str = "/var/lib/emerge-ai/tiers.json",
    plan_fn=build_plan,
    protect_fn=None,
    cleanup_fn=None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-V"):
        text, code = _version_text()
        print(text, end="")
        return code

    if argv and argv[0] == "--help":
        print(OWN_FLAG_HELP)
        print("Run 'emerge-ai -h' (or any emerge option) for emerge's own help.")
        return 0

    mode, emerge_args = parse_own_flags(argv)

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
        rc = run_emerge(emerge_args, emerge_binary=emerge_binary)
        state.transition(run, state.DONE if rc == 0 else state.INCIDENT, runs_dir)
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
        rc = run_emerge(merge_args, emerge_binary=emerge_binary)
        if rc == 0 and (prot.snapshot or prot.archive_dir):
            for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                print(f"emerge-ai: {line}", file=sys.stderr)
        state.transition(run, state.DONE if rc == 0 else state.INCIDENT, runs_dir)
        return rc

    state.transition(run, state.DONE, runs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
