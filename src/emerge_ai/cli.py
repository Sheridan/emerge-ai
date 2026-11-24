"""CLI: own flags, compat gate, passthrough, -a/-p interception, plan enrichment, run states."""

from __future__ import annotations

import inspect
import os
import re
import sys
import time
from pathlib import Path
from dataclasses import asdict
from urllib.parse import quote

from emerge_ai import __version__, portage_compat, state
from emerge_ai.compat import check_version_compat
from emerge_ai.config import Config, ConfigError, load_config
from emerge_ai.doctor import doctor_report, is_mass_update
from emerge_ai.enrich import plan_digest
from emerge_ai.flags import OWN_FLAG_HELP, parse_own_flags
from emerge_ai import changelog, config_edit, digest, etcupdate
from emerge_ai import gate as gate_mod, init_check
from emerge_ai import overlay as overlay_mod
from emerge_ai.incident import build_incident
from emerge_ai.llm import LLMClient, LLMError
from emerge_ai.plan import build_plan, build_plan_from_output
from emerge_ai import rollback as rollback_mod
from emerge_ai.rollback import Protection
from emerge_ai.runner import confirm, drop_flags, flag_present, run_emerge_capturing
from emerge_ai.tiers import TierService, snapshot_required
from emerge_ai import ui

PRETEND_FLAGS = ("-p", "--pretend")
ASK_FLAGS = ("-a", "--ask")
VERBOSE_FLAGS = ("-v", "--verbose")


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
        print(ui.err(exc), file=sys.stderr)
        return 3
    result = check_version_compat(pv, __version__)
    if not result.ok:
        print(ui.err(result.message), file=sys.stderr)
        return 4
    return None


def _make_tier_service(cfg: Config, cache_path=None, show_reasoning=False):
    client = None
    if cfg.endpoint:
        try:
            client = LLMClient(cfg, show_reasoning=show_reasoning)
        except LLMError as exc:
            print(ui.warn(f"{exc}; tiers fall back to conservative"), file=sys.stderr)
    return TierService(client, cache_path=cache_path)


def _default_protect(run, plan) -> Protection:
    # D4 (plan-before-plain-merge): with plan=None the tiers are unknown and
    # the spec demands protection exactly then — protect unconditionally
    return rollback_mod.protect(run.run_id, plan, contents_fn=portage_compat.vdb_contents)


def _mutation_gate(mode, plan, *, audit_path=gate_mod.AUDIT_PATH, audit_fn=gate_mod.audit):
    """Autonomy-matrix verdict for the merge about to run (spec: agent-loop-
    consent). AUTO/DENY decisions are audited; under --noninteractive an AUTO
    without a written audit line is void (fail-closed). Interactive ASK needs
    no extra consent: the operator's TTY invocation (plain runs) or the
    explicit Proceed? (-a) already happened."""
    mode_dict = asdict(mode)
    tiers = tuple(sorted({e.tier for e in plan.entries})) if plan is not None else ()
    variant = gate_mod.Variant(
        key="merge",
        title="merge queue" + (f" (tiers {tiers})" if tiers else " (tiers unknown)"),
        risks=[f"tier {t} packages in queue" for t in tiers] or ["tiers unknown: queue not classifiable"],
        kind="merge",
        tiers=tiers,
    )
    verdict, reason = gate_mod.autonomy_decision(mode_dict, variant)
    if verdict in (gate_mod.AUTO, gate_mod.DENY):
        written = audit_fn(
            {
                "mode": mode_dict,
                "variant": "merge",
                "kind": "merge",
                "tiers": list(tiers),
                "decision": "apply" if verdict == gate_mod.AUTO else "denied",
                "autonomy": verdict,
                "reason": reason,
            },
            audit_path,
        )
        if not written:
            if mode.noninteractive:
                return False, reason + " (decision audit unwritable: fail-closed)"
            print(ui.warn("decision audit could not be written"), file=sys.stderr)
    if verdict == gate_mod.DENY:
        return False, reason
    return True, reason


def _rollback_mode(
    mode,
    *,
    list_fn=None,
    rollback_fn=rollback_mod.rollback,
    executor=None,
    confirm_fn=confirm,
    input_fn=None,
) -> int:
    """--rollback recovery mode: show recovery points, restore the chosen one
    through the guarded channel; emerge is never started here."""
    recs = (list_fn or rollback_mod.list_protections)()
    if not recs:
        print(ui.err("no recovery points found (nothing to restore)."), file=sys.stderr)
        return 5
    print("recovery points:", file=sys.stderr)
    usable = []
    for i, r in enumerate(recs, 1):
        pkgs = ", ".join(p.get("cpv", "?") for p in r.packages[:4]) or "unknown queue"
        flag = " [failed]" if r.failed else " [artifact missing]" if r.missing else ""
        print(
            f"  {i}. {r.run_id}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(r.created))}"
            f"  {r.kind}  {pkgs}{flag}",
            file=sys.stderr,
        )
        if not r.failed and not r.missing:
            usable.append((i, r))
    if not usable:
        print(ui.err("no usable recovery point (all failed or lost)."), file=sys.stderr)
        return 5
    if mode.noninteractive and not mode.responsibility:
        print(
            ui.err(
                "--noninteractive: refusing to restore without "
                "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences; "
                "nothing was changed. Manual restore: re-run interactively, or restore "
                f"{usable[-1][1].path} yourself (btrfs snapshot swap / tar -x rootfs)."
            ),
            file=sys.stderr,
        )
        return 5
    idx = usable[-1][0]  # newest by default
    if not mode.noninteractive:
        try:
            answer = (input_fn or input)(  # builtins lookup at call time: test-patchable
                ui.prompt(f"Recovery point to restore [{usable[-1][0]}] (1-{usable[-1][0]}): ")
            ).strip()
        except EOFError:
            answer = ""
        if answer.isdigit() and 1 <= int(answer) <= usable[-1][0]:
            wanted = int(answer)
            idx = next((i for i, r in usable if i == wanted), idx)
    rec = next(r for i, r in usable if i == idx)
    prot = Protection(
        run_id=rec.run_id,
        snapshot=rec.path if rec.kind == "snapshot" else None,
        archive_dir=rec.path if rec.kind == "archive" else None,
    )
    outcome = rollback_fn(
        prot,
        responsibility=mode.responsibility,
        confirm_fn=confirm_fn,
        executor=executor or rollback_mod.restore_archive,
        root_subvolume=rec.kind == "snapshot",
    )
    print(outcome.text, file=sys.stderr)
    return 0


def _offer_rollback(
    mode,
    prot: Protection,
    run,
    *,
    confirm_fn=confirm,
    rollback_fn=rollback_mod.rollback,
    executor=None,
) -> None:
    """Offer after a failed merge (spec: system-rollback): responsibility flag
    restores on its own, interactive asks with consequences, plain
    --noninteractive only hints — artifacts are never dropped silently."""
    if not (prot.snapshot or prot.archive_dir):
        return  # rest-tier queue: no recovery point was ever created
    if mode.responsibility:
        run.rollback = (
            rollback_fn(
                prot,
                responsibility=True,
                confirm_fn=confirm_fn,
                executor=executor or rollback_mod.restore_archive,
                root_subvolume=bool(prot.snapshot),
            ).kind
        )
    elif mode.noninteractive:
        run.rollback = "offered-skipped"
        print(
            ui.warn(
                "recovery point saved, nothing restored in --noninteractive; "
                "run `emerge-ai --rollback` to restore it (artifacts kept)"
            ),
            file=sys.stderr,
        )
    else:
        run.rollback = (
            rollback_fn(
                prot,
                responsibility=False,
                confirm_fn=confirm_fn,
                executor=executor or rollback_mod.restore_archive,
                root_subvolume=bool(prot.snapshot),
            ).kind
        )
    if run.rollback:
        print(ui.info(f"rollback channel: {run.rollback}"), file=sys.stderr)


REPAIR_LIMIT = 2  # apply->retry cycles per run (spec: agent-loop-consent)


def _variant_tiers(spec: dict, plan) -> tuple:
    """Risk tier of a whitelist variant: the queue/packages it touches when
    known, conservative (1) when the plan or the target is unknown."""
    from emerge_ai.plan import package_of

    if plan is None:
        return (1,)
    action = spec.get("action") or {}
    keys = set()
    if action.get("type") == "overlay-copy":
        keys.add(package_of(action["cpv"]))
    for line in action.get("lines", []):
        keys.add(package_of(line))
    tiers = [e.tier for e in plan.entries if not keys or package_of(e.cpv) in keys]
    return (max(tiers),) if tiers else (1,)


def _apply_action(action: dict, *, run, etc_dir: str = "/etc/portage", overlay_root=None) -> None:
    """Whitelist interpreter — the only code mutating the system in the repair
    loop; model output is never read here, actions are built by typed_variants."""
    t = (action or {}).get("type", "retry")
    if t in ("retry", "env-retry"):
        return  # the change happens through the retried emerge call
    if t == "package-edit":
        # idempotent: existing (commented) line with the same directive is skipped
        for line in action["lines"]:
            want = line.split()
            etc = Path(etc_dir)
            if etc.is_dir():
                dup = any(
                    ln.strip() and not ln.lstrip().startswith("#") and
                    ln.split()[: len(want)] == want
                    for f in etc.rglob("*") if f.is_file()
                    for ln in f.read_text(errors="ignore").splitlines()
                )
                if dup:
                    print(ui.info(f"package.{action['kind']}: '{line}' already present — skipped"),
                          file=sys.stderr)
                    continue
            config_edit.apply_package_edit(
                action["kind"], line, reason=action["reason"],
                journal_id=run.run_id, etc_dir=etc_dir,
            )
        return
    if t == "overlay-copy":
        cpv = action["cpv"]
        cat, pn, _pv = overlay_mod._split_cpv(cpv)
        import portage  # production-only path: tests inject the seam

        src = Path(portage.settings["PORTDIR"]) / cat / pn
        kwargs = {"reason": "emerge-ai repair copy", "journal_id": run.run_id}
        if overlay_root:
            kwargs["repo_root"] = overlay_root
        overlay_mod.add_package(cpv, source_dir=src, **kwargs)
        return
    raise ValueError(f"unknown repair action {t!r}")  # fail-closed, never executed


def _incident_flow(
    run,
    mode,
    plan,
    *,
    audit_path,
    etc_dir: str = "/etc/portage",
    overlay_root=None,
    gate_fn=None,
    confirm_fn=confirm,
    input_fn=None,
    interactive: bool = False,
) -> dict | None:
    """Typed variants -> consent gate (autonomy matrix when not interactive:
    --noninteractive or no terminal) -> apply one. Returns the applied spec
    (its action["env"] may modify the retry), or None — advisory stays the
    floor in every refusal."""
    if len(run.repair) >= REPAIR_LIMIT:
        print(
            ui.warn(
                f"agent loop: repair limit ({REPAIR_LIMIT} apply->retry cycles) reached; "
                "showing the final report only"
            ),
            file=sys.stderr,
        )
        return None
    from emerge_ai.agent import typed_variants

    specs = typed_variants(run.incident or {})
    mode_dict = asdict(mode)

    def bound(spec):
        def _go():
            _apply_action(spec["action"], run=run, etc_dir=etc_dir, overlay_root=overlay_root)
            run.repair.append({"attempt": len(run.repair) + 1, "variant": spec["key"]})
            print(ui.ok(f"applied repair variant [{spec['key']}], retrying emerge"), file=sys.stderr)

        return _go

    variants = []
    for s in specs:
        tiers = _variant_tiers(s, plan)
        variants.append(
            gate_mod.Variant(
                key=s["key"], title=s["title"], pros=[s.get("rationale", "")], cons=[],
                risks=[f"affects tier {tiers[0]}"], kind="fix", tiers=tiers,
                action=bound(s),
            )
        )
    try:
        if not interactive:
            # matrix path: never blocks on a terminal that isn't there
            autos = [
                (s, v)
                for s, v in zip(specs, variants)
                if gate_mod.autonomy_decision(mode_dict, v)[0] == gate_mod.AUTO
            ]
            if not autos:
                print(
                    ui.info(
                        "consent gate: auto-repair refused at tiers "
                        f"{_variant_tiers(specs[0], plan)} — run interactively or pass "
                        "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences"
                    ),
                    file=sys.stderr,
                )
                return None  # matrix denies: advisory as before
            spec, v = autos[-1]  # most specific fix (retry is always first)
            verdict, reason = gate_mod.autonomy_decision(mode_dict, v)
            if not gate_mod.audit(
                {"mode": mode_dict, "variant": v.key, "kind": "fix",
                 "decision": "apply", "autonomy": verdict, "reason": reason},
                audit_path,
            ):
                print(ui.warn("repair: decision audit unwritable — fail-closed, nothing applied"),
                      file=sys.stderr)
                return None
            v.action()
            print(ui.info(f"autonomy matrix: {reason}"), file=sys.stderr)
            return spec
        decision = (gate_fn or gate_mod.gate)(
            variants, mode=mode_dict, confirm_fn=confirm_fn,
            input_fn=input_fn or (lambda prompt: input(prompt)),  # patchable at call time
            audit_path=audit_path,
        )
        if decision.get("status") != "applied":
            print(ui.info(f"consent gate: {decision.get('status')} — system untouched"),
                  file=sys.stderr)
            return None
        return next(sp for sp in specs if sp["key"] == decision.get("variant"))
    except Exception as exc:  # the loop must never mask the original failure
        print(ui.err(f"repair loop skipped: {exc}"), file=sys.stderr)
        return None


def _stdin_is_tty() -> bool:
    """Interactive means a real terminal on stdin; captured or closed stdin is not."""
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def _call_agent_fn(agent_fn, incident: dict, interactive: bool):
    """Call the agent seam. Older agent_fn take only the incident; newer ones may
    accept an `interactive` keyword — the signature stays backward compatible."""
    try:
        params = inspect.signature(agent_fn).parameters
    except (TypeError, ValueError):  # builtins, functools wrappers without a signature
        params = {}
    takes_interactive = "interactive" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if takes_interactive:
        return agent_fn(incident, interactive=interactive)
    return agent_fn(incident)


def _maybe_agent(
    run, config_path, agent_fn=None, show_reasoning=False, interactive: bool = False
) -> str | None:
    if not run.incident:
        return None
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        return
    if not cfg.endpoint:
        print(ui.err("no LLM endpoint configured; agent consultation skipped"), file=sys.stderr)
        return None
    print(ui.info("incident -> consulting agent (proposal is advisory; executable "
                  "whitelist variants follow below)..."), file=sys.stderr)
    try:
        if agent_fn is not None:
            proposal = _call_agent_fn(agent_fn, run.incident, interactive)
        else:
            from emerge_ai.agent import IncidentAgent
            from emerge_ai.prompts import collect_context

            client = LLMClient(cfg, show_reasoning=show_reasoning)
            info = portage_compat.emerge_info()
            agent = IncidentAgent(
                client, context=collect_context(info, cfg.language)
            )
            proposal = agent.propose(
                run.incident,
                render_to=sys.stderr if show_reasoning else None,
                interactive=interactive,
            ).proposal
        print(ui.info("agent proposal:"), file=sys.stderr)
        ui.paint_llm_block(proposal, cfg.llm_colors, sys.stderr)
        return proposal
    except Exception as exc:  # agent must never mask the original failure rc
        print(ui.err(f"agent unavailable: {exc}"), file=sys.stderr)
        return None


_PKG_NAME = r"[A-Za-z0-9+_][A-Za-z0-9+._-]*"
_PKG_USE_PATH_RE = re.compile(
    rf"package\.(?:use|accept_keywords|mask|unmask)[^/]*/({_PKG_NAME})/({_PKG_NAME})/?$")
_ETC_SUFFIX_RE = re.compile(r"(\.pre-emerge-ai|_etc-update-new)$|-r\d+$")


def _pkg_docs(sandbox, path: str) -> list[tuple[str, str]]:
    """Web documentation context for one config file (spec: etc-update-llm).

    A <cat>/<pn> pair under package.use*/package.accept_keywords/package.mask/
    package.unmask resolves to its packages.gentoo.org page; anything else
    falls back to a wiki search on the file's basename. Every failure mode
    (fetch error, empty page) yields [] with a warning — never an exception,
    so an unreachable network cannot skip the LLM decision (design D3).
    """
    m = _PKG_USE_PATH_RE.search(path)
    if m:
        url = f"https://packages.gentoo.org/packages/{m.group(1)}/{m.group(2)}"
    else:
        q = _ETC_SUFFIX_RE.sub("", Path(path).name)
        url = f"https://wiki.gentoo.org/index.php?search={quote(q, safe='')}&fulltext=1"
    try:
        r = sandbox.web_fetch(url)
    except Exception as exc:  # web_fetch itself shouldn't raise, belt-and-braces
        r = {"error": str(exc)}
    if "content" not in r or not r["content"].strip():
        reason = r.get("error", "empty response")
        print(ui.warn(f"web docs unavailable for {path}: {reason}"), file=sys.stderr)
        return []
    return [(r["url"], r["content"])]


def _etc_flow(run, config_path, *, llm=True, input_fn=input, client_factory=None, show_reasoning=False) -> None:
    if not run.incident or run.incident.get("class") != "config-protect":
        return
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    paths = etcupdate.detect(run.incident.get("stderr_tail", ""))
    if not paths:
        return
    print(ui.warn("config-protect detected: " + ", ".join(paths)), file=sys.stderr)
    for newp in paths:
        try:
            print(etcupdate.show_diff(newp, stream=sys.stderr), file=sys.stderr)
        except OSError as exc:
            print(ui.warn(f"no diff for {newp}: {exc}"), file=sys.stderr)
    if not llm or not cfg.etc_update_after_build:
        print(ui.info("etc_update_after_build off or raw passthrough — showing diffs only, no actions"),
              file=sys.stderr)
        return
    if client_factory is None:
        client_factory = LLMClient
    sandbox = None
    if cfg.web_access:
        from emerge_ai.sandbox import Sandbox

        sandbox = Sandbox()  # one sandbox for the whole flow, not per file
    for newp in paths:
        current = etcupdate.original_of(newp)
        if not Path(newp).exists():
            continue
        # web phase never raises: fetch trouble yields [] (spec: network is
        # not a precondition for the LLM decision)
        docs = etcupdate.collect_docs(current, web_fetch=None if sandbox is None else lambda p: _pkg_docs(sandbox, p))
        try:
            decision = etcupdate.llm_decide(client_factory(cfg, show_reasoning=show_reasoning), newp, current, docs, cfg.resolved_language())
        except Exception as exc:  # now genuinely LLM-only (design D4)
            print(ui.err(f"etc LLM unavailable: {exc}"), file=sys.stderr)
            continue
        print(ui.info(f"LLM decision: {decision['action']} — {decision.get('reason', '')}"),
              file=sys.stderr)
        for c in decision.get("citations", []):
            print(ui.info(f"  cite: {c}"), file=sys.stderr)
        try:
            ans = input_fn(ui.prompt("Apply LLM decision [Y/n/c=override action[:file]]? ")).strip()
            decision = etcupdate.parse_override(ans, decision)
        except EOFError:
            decision = {"action": "keep-current", "reason": "no input", "citations": ["prompt-eof"]}
        except ValueError as exc:
            print(ui.warn(f"bad override ({exc}); keeping current"), file=sys.stderr)
            decision = {"action": "keep-current", "reason": "bad override", "citations": ["user"]}
        # deliberate: per-file consent already happened above via
        # input_fn/parse_override; apply_decision requires the keyword gate
        res = etcupdate.apply_decision(newp, decision, confirm_fn=lambda _p: True)
        print(ui.info(f"etc-update applied={res['applied']} action={res['action']}"), file=sys.stderr)



def _resolve_resume(emerge_args: list[str], mode, runs_dir) -> tuple[state.RunState, list[str]]:
    """Handle --resume, returning (run, emerge_args).

    An incomplete emerge-ai run is continued and --resume is stripped from the
    emerge argv. Without such a run the flag stays put: emerge resumes its own
    interrupted merge, emerge-ai just registers a regular run around it.
    """
    if "--resume" not in emerge_args:
        run = state.new_run(emerge_args, mode)
        state.save_run(run, runs_dir)
        return run, emerge_args
    run = state.latest_incomplete(runs_dir)
    if run is None:
        print(ui.info("--resume: no incomplete emerge-ai run; passing --resume to emerge"),
              file=sys.stderr)
        run = state.new_run(emerge_args, mode)
        state.save_run(run, runs_dir)
        return run, emerge_args
    print(
        ui.info(
            f"resuming run {run.run_id} (state {run.state}"
            + (f", incident: {run.incident['class']})" if run.incident else ")")
        ),
        file=sys.stderr,
    )
    return run, [a for a in emerge_args if a != "--resume"]


def _post_run_digest(run, output, config_path, runs_dir) -> None:
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    if cfg.show_digest:
        print(digest.post_run_digest(run, output), file=sys.stderr)
    if cfg.changelog_digest and run.plan:
        # automatic changelog digest after a successful run (spec: run-reporting);
        # source or LLM failures must not touch the run's exit code
        try:
            client = LLMClient(cfg) if cfg.endpoint else None
            text = changelog.collect_digest(
                gh_repos=cfg.gh_repos, git_urls=cfg.git_urls, news_dir=cfg.news_dir,
                client=client, packages=[e["cpv"] for e in run.plan],
            )
            if client is not None:
                ui.paint_llm_block(text, cfg.llm_colors, sys.stderr)
            else:
                print(text, file=sys.stderr)
            run.changelog = ui.strip_ansi(text)
        except Exception as exc:
            print(ui.warn(f"changelog digest skipped: {exc}"), file=sys.stderr)


def _changelog_mode(config_path, show_reasoning=False) -> int:
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        cfg = Config()
    client = LLMClient(cfg, show_reasoning=show_reasoning) if cfg.endpoint else None
    text = changelog.collect_digest(
        gh_repos=cfg.gh_repos, git_urls=cfg.git_urls, news_dir=cfg.news_dir, client=client
    )
    if client is not None:
        ui.paint_llm_block(text, cfg.llm_colors, sys.stdout)
    else:
        print(text)
    return 0


def _meta_command(argv: list[str]) -> int | None:
    """Handle emerge-ai's own meta commands: --version/-V and --help.

    Rule: only argv[0] selects an emerge-ai mode; in any other position these
    strings are ordinary emerge arguments and are passed through. Runs before
    the compat gate: help and version must work on any host.
    """
    if argv and argv[0] in ("--version", "-V"):
        text, code = _version_text()
        print(text, end="")
        return code
    if argv and argv[0] == "--help":
        print(OWN_FLAG_HELP)
        print("Run 'emerge-ai -h' (or any emerge option) for emerge's own help.")
        return 0
    return None


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
    systemd_check=init_check.is_systemd,
    audit_path: str | None = None,  # None -> gate.AUDIT_PATH at call time (test-injectable)
    protection_list_fn=None,
    rollback_fn=None,
    rollback_executor=None,
    gate_fn=None,
    confirm_fn=confirm,
    input_fn=None,
    etc_dir: str = "/etc/portage",
) -> int:
    if argv is None:
        argv = sys.argv[1:]
    runs_dir = runs_dir or os.environ.get("EMERGE_AI_RUNS_DIR") or state.RUNS_DIR
    tiers_cache = os.environ.get("EMERGE_AI_TIERS_CACHE") or tiers_cache

    meta = _meta_command(argv)
    if meta is not None:
        return meta

    mode, emerge_args = parse_own_flags(argv)
    verbose = flag_present(emerge_args, VERBOSE_FLAGS)

    if mode.changelog:
        if not systemd_check():
            print(ui.warn(f"no systemd detected (init: {init_check.detected_init()}) — "
                          "changelog digest is read-only and continues"), file=sys.stderr)
        return _changelog_mode(config_path, verbose)

    blocked = _compat_gate()
    if blocked is not None:
        return blocked

    # systemd-only support (spec: cli-compat): refuse before any mutation;
    # read-only (pretend) modes warn and work, unknown init fails closed
    if not systemd_check():
        init_name = init_check.detected_init()
        if flag_present(emerge_args, PRETEND_FLAGS):
            print(ui.warn(f"no systemd detected (init: {init_name}) — "
                          "read-only modes only, plan proceeds without changes"),
                  file=sys.stderr)
        else:
            print(ui.err(
                "emerge-ai supports systemd hosts only; "
                f"detected init: {init_name}; refusing to mutate this system (emerge not started)"
            ), file=sys.stderr)
            return 6

    if mode.rollback:  # recovery channel (spec: system-rollback): never emerges
        return _rollback_mode(
            mode,
            list_fn=protection_list_fn,
            rollback_fn=rollback_fn or rollback_mod.rollback,
            executor=rollback_executor,
        )

    run, emerge_args = _resolve_resume(emerge_args, mode, runs_dir)

    pretend = flag_present(emerge_args, PRETEND_FLAGS)
    ask = flag_present(emerge_args, ASK_FLAGS)
    # The operator can answer only here: -p and --noninteractive stay question-free.
    interactive = not pretend and not mode.noninteractive and _stdin_is_tty()

    # Common pre-merge block (design D1): every run passes through plan ->
    # tiers -> digest/doctor; mutation runs additionally through protect
    # BEFORE any mode-specific confirmation (D2). -p stops after the plan.
    if run.state == state.VERSION_CHECK:
        state.transition(run, state.PLAN, runs_dir)
    plan_args = drop_flags(list(emerge_args), ASK_FLAGS)
    if not pretend:
        plan_args.append("--pretend")
    # On the plain mutation path stdout must stay a byte-for-byte merge
    # passthrough, so all plan-phase output mirrors to stderr (D3);
    # -p/-a keep it on stdout as run-reporting normalizes.
    plan_stream = sys.stdout if (pretend or ask) else sys.stderr
    rc, output = run_emerge_capturing(
        plan_args, emerge_binary=emerge_binary, stdout_stream=plan_stream
    )
    while rc != 0:  # repair loop for the resolve phase (wire-agent-apply-loop)
        incident = build_incident(rc, output, plan_args)
        incident["class"] = "plan-failed"
        run.incident = incident
        if run.state != state.INCIDENT:  # resumed run may already sit in INCIDENT
            state.transition(run, state.INCIDENT, runs_dir)
        else:
            state.save_run(run, runs_dir)
        proposal = _maybe_agent(
            run, config_path, agent_fn, show_reasoning=verbose, interactive=interactive
        )
        run.agent_proposal = proposal
        applied = None
        if proposal is not None:
            # the loop is engaged only when the agent layer took part; with no
            # agent the CLI keeps its pre-loop, purely consultative behaviour
            applied = _incident_flow(
                run, mode, None,
                audit_path=audit_path or gate_mod.AUDIT_PATH,
                etc_dir=etc_dir, gate_fn=gate_fn, input_fn=input_fn,
                confirm_fn=confirm_fn,
                interactive=interactive,
            )
        if applied is None:
            state.save_run(run, runs_dir)
            return rc
        state.save_run(run, runs_dir)
        rc, output = run_emerge_capturing(
            plan_args, emerge_binary=emerge_binary, stdout_stream=plan_stream,
            env=(applied.get("action") or {}).get("env"),
        )

    plan = None
    try:
        cfg = load_config(config_path)
        tier_service = _make_tier_service(cfg, cache_path=tiers_cache, show_reasoning=verbose)
        # reuse the pretend run we already captured; only unparseable output
        # (quiet formats) pays for the resolver again (avoid-double-resolve)
        plan = build_plan_from_output(output, emerge_args, tier_service, fallback=plan_fn)
        run.plan = [asdict(e) for e in plan.entries]
        state.save_run(run, runs_dir)
        summarize = None
        if cfg.endpoint:  # LLM summary atop the deterministic core (spec: run-reporting)
            _llm = LLMClient(cfg, show_reasoning=verbose)

            def summarize(messages, _c=_llm):
                return _c.chat(messages)

        print(plan_digest(plan, stream=plan_stream, summarize=summarize), file=plan_stream)
        if is_mass_update(emerge_args, plan):
            for line in doctor_report(plan, stream=sys.stderr):
                print(line, file=sys.stderr)
    except Exception as exc:  # enrichment must never break emerge's own flow
        print(ui.warn(f"plan enrichment skipped: {exc}"), file=sys.stderr)

    if pretend:
        if ask:
            # pretend dominates (spec: cli-compat): plan-only, question-free,
            # merge is never reachable with --pretend, even combined with --ask
            print(
                ui.info("--pretend takes precedence over --ask: plan shown, merge not started"),
                file=sys.stderr,
            )
        state.transition(run, state.DONE, runs_dir)
        return 0

    # --- mutation path: protection first (system-rollback spec, D2) ---
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
    elif plan is not None and not snapshot_required(plan.entries):
        # system-rollback: rest-tier-only queue gets no recovery point
        prot = Protection(run_id=run.run_id)
    else:
        prot = pfn(run, plan)
    for note in prot.notes:
        print(ui.info(note), file=sys.stderr)
    run.protection = {
        "snapshot": prot.snapshot,
        "archive": prot.archive_dir,
        "failed": prot.failed,
    }
    state.save_run(run, runs_dir)

    # D4: with an unresolvable plan tiers are unknown, and the spec demands
    # protection exactly then — a failed snapshot aborts either way
    if prot.failed and (plan is None or snapshot_required(plan.entries)):
        queue = "an unresolvable queue" if plan is None else "a tier<=4 queue"
        print(ui.err(f"FAILED to create a recovery point for {queue}."), file=sys.stderr)
        if mode.noninteractive or not confirm(
            ui.prompt(
                "emerge-ai: merge without recovery point is unsafe. Proceed anyway? [y/N] "
            )
        ):
            print(ui.err("aborted: no recovery point."), file=sys.stderr)
            for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                print(ui.ok(line), file=sys.stderr)  # D5: leave nothing behind
            state.transition(run, state.DONE, runs_dir)
            return 5

    queue_tiers = sorted({e.tier for e in plan.entries}) if plan is not None else []
    tiers_note = f" (queue tiers: {', '.join(map(str, queue_tiers))})" if queue_tiers else ""
    if ask and not mode.noninteractive:
        if not confirm(ui.prompt(f"Proceed?{tiers_note} [y/N] ")):
            print(ui.info("aborted by user."), file=sys.stderr)
            if prot.snapshot or prot.archive_dir:
                for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                    print(ui.ok(line), file=sys.stderr)  # D5: no merge -> no point
            state.transition(run, state.DONE, runs_dir)
            return 0

    # autonomy gate (spec: agent-loop-consent): the matrix decides and audits
    # every mutation merge; the printed line carries the actual verdict (D4)
    allowed, gate_reason = _mutation_gate(mode, plan, audit_path=audit_path or gate_mod.AUDIT_PATH)
    if allowed:
        print(ui.info(f"autonomy gate: {gate_reason}"), file=sys.stderr)
    else:
        print(ui.err(f"autonomy gate: merge blocked — {gate_reason}"), file=sys.stderr)
        if prot.snapshot or prot.archive_dir:
            for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                print(ui.ok(line), file=sys.stderr)  # blocked before mutations
        state.transition(run, state.DONE, runs_dir)
        return 7

    merge_args = drop_flags(emerge_args, ASK_FLAGS + PRETEND_FLAGS)
    state.transition(run, state.MERGE, runs_dir)
    rc, output = run_emerge_capturing(merge_args, emerge_binary=emerge_binary)
    while rc != 0:  # failure -> agent -> consent gate -> apply -> retry (spec: agent-loop-consent)
        run.incident = build_incident(rc, output, merge_args)
        state.transition(run, state.INCIDENT, runs_dir)
        proposal = _maybe_agent(
            run, config_path, agent_fn, show_reasoning=verbose, interactive=interactive
        )
        run.agent_proposal = proposal
        applied = None
        if proposal is not None:
            applied = _incident_flow(
                run, mode, plan,
                audit_path=audit_path or gate_mod.AUDIT_PATH,
                etc_dir=etc_dir, gate_fn=gate_fn, input_fn=input_fn,
                confirm_fn=confirm_fn,
                interactive=interactive,
            )
        if applied is None:
            break
        state.transition(run, state.MERGE, runs_dir)  # INCIDENT -> MERGE exists
        rc, output = run_emerge_capturing(
            merge_args, emerge_binary=emerge_binary,
            env=(applied.get("action") or {}).get("env"),
        )
        run.repair[-1]["retry_rc"] = rc
    if rc == 0:
        if prot.snapshot or prot.archive_dir:
            for line in (cleanup_fn or rollback_mod.cleanup)(prot):
                print(ui.ok(line), file=sys.stderr)
        state.transition(run, state.DONE, runs_dir)
        _post_run_digest(run, output, config_path, runs_dir)
    else:  # run stays in INCIDENT: advisory report, rollback offer, etc flow
        _offer_rollback(
            mode,
            prot,
            run,
            rollback_fn=rollback_fn or rollback_mod.rollback,
            executor=rollback_executor,
        )
        if ask:
            _etc_flow(run, config_path, show_reasoning=verbose)
        else:
            _etc_flow(run, config_path, llm=False)
    state.save_run(run, runs_dir)
    return rc


if __name__ == "__main__":
    sys.exit(main())
