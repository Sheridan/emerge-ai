"""Consent dialog (spec: consent-dialogue, design D1-D7).

One question stands before every mutation in an interactive run: the recovery
point contract (printed before the point exists) plus a numbered list whose
every item is an executable whitelist scenario. A number runs through the
gate's execution core (autonomy matrix + audit); the operator's own text goes
to the model channel, the menu comes back — rounds are unlimited, the guard
is the operator themselves (abort in every round, EOF, ctrl-c). The channel
is a dialogue (ConsentDialogue): it remembers its rounds, answers the
operator's question first, and reads evidence with read-only tools.
Without an endpoint the dialog still works: free-text reprints the menu with
a note.

The model may comment and reorder variants by key; a variant without a typed
spec has no action and cannot exist, so the model never invents commands (D8).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field

from emerge_ai import (agent, config_edit, gate, injection, llm, prompts, rollback,
                       triage, ui)

MENU_CAP = 6  # the ask_operator option cap, reused for the consent menu


@dataclass
class MenuSpec:
    """A consent menu line before binding: the action dict is executed by
    cli._apply_action through the gate core — nothing here runs itself."""

    key: str
    title: str
    kind: str  # merge | fix
    tiers: tuple[int, ...] = (5,)
    detail: list[str] = field(default_factory=list)
    action: dict | None = None


def _fmt_tiers(tiers) -> str:
    return ", ".join(map(str, tiers)) if tiers else "unknown"


def protect_contract(plan, *, fs: str, run_id: str,
                     snap_base: str = rollback.SNAP_BASE,
                     archive_base: str = rollback.ARCHIVE_BASE,
                     user_data=rollback.USER_DATA_PREFIXES) -> list[str]:
    """The recovery-point block shown before the point exists (spec:
    system-rollback delta): mechanism, path, exclusions, an honest rollback
    sentence per actual point kind, auto-delete disclosure. Pure formatting —
    creating anything here would break the contract itself."""
    from emerge_ai.tiers import snapshot_required

    lines = ["recovery point contract (nothing is created before you answer):"]
    if plan is not None and not snapshot_required(plan.entries):
        lines.append("  none required: the queue is rest-tier only")
        return lines
    if fs == "btrfs":
        lines.append(f"  kind: read-only btrfs snapshot at {snap_base}/{run_id}")
        lines.append("  rollback: online restore is NOT possible on a snapshot — "
                     "`emerge-ai --rollback` prints the rescue-mode steps")
    else:
        lines.append(f"  kind: file archive at {archive_base}/{run_id}"
                     + (f" (root fs: {fs}, no snapshot support)" if fs != "unknown" else ""))
        lines.append("  rollback: `emerge-ai --rollback` restores the files online, "
                     "no reboot needed")
    lines.append("  not saved: " + ", ".join(user_data))
    lines.append("  after a successful merge the point is deleted automatically — "
                 "rolling back a merge that worked is not possible")
    return lines


def _as_findings(verdict) -> list:
    """The verdict may arrive as triage.Verdict or as the run-state dict
    (run.triage = verdict.to_dict()); findings are rebuilt as Finding objects
    so triage.candidates() keeps its typed interface."""
    if verdict is None:
        return []
    findings = verdict.get("findings", []) if isinstance(verdict, dict) else verdict.findings
    return [triage.Finding(**f) if isinstance(f, dict) else f for f in findings]


def menu_specs(verdict, plan, *, world: list[str] | None = None,
               etc_dir: str = "/etc/portage") -> tuple[list[MenuSpec], list[str]]:
    """Deterministic menu (design D2/D6): clean plan -> [merge]; degraded ->
    executable typed fixes (config_edit whitelist kinds, the etcupdate
    channel, the whitelisted commands) + [merge as-is] with the
    unresolved-finding count. `world` (atoms, read via portage_compat) is the
    first validation pass of task 1.2 — a deselect whose atom left world is
    not shown at all. `etc_dir` is the same directory the apply channel writes
    to, so a `package.*` line names the file it really lands in — a
    category-layout host is told `package.accept_keywords/dev-libs` (spec:
    repair-actions, design D7). Non-executable advice never enters the list —
    it comes back as manual lines to print outside it. Cap MENU_CAP; merge is
    never cut, the least specific fixes fall off first."""
    tiers = tuple(sorted({e.tier for e in plan.entries})) if plan is not None else ()
    n = len(plan.entries) if plan is not None else 0
    # an unbuilt plan is not an empty queue (spec: consent-dialogue,
    # fix-queued-plan-parsing): the operator must never consent to a merge
    # described as "0 package(s)" when nobody actually counted
    if plan is None:
        queue_text = "queue unknown: the plan could not be built"
    elif n:
        queue_text = f"{n} package(s), tiers {_fmt_tiers(tiers)}"
    else:
        queue_text = "0 package(s)"
    specs: list[MenuSpec] = []
    manual: list[str] = []
    degraded = bool(verdict.get("status") == triage.DEGRADED if isinstance(verdict, dict)
                    else verdict is not None and verdict.degraded)
    findings = _as_findings(verdict)
    if degraded:
        seen_paths: set[str] = set()
        for f in findings:
            if f.kind != "config-updating":
                continue
            m = triage.CONFIG_UPDATING_RE.search(f.evidence)
            path = m.group(1) if m else None
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            specs.append(MenuSpec(
                key=f"etc-{path.rsplit('/', 1)[-1]}",
                title=f"resolve the pending config update for {path}",
                kind="fix",
                detail=["the per-file etc-update dialogue still asks you per file",
                        "undo: the replaced file is kept as .pre-emerge-ai"],
                action={"type": "etc-update", "path": path},
            ))
        for cand in triage.candidates(findings, world=world):
            if not cand["executable"]:
                text = f"  manual (system cannot execute this yet): {cand['text']}"
                if text not in manual:
                    manual.append(text)
            elif cand["kind"] == "accept_keywords":
                line = cand["text"]
                cpv = line.split()[0].lstrip("=") if line.split() else "?"
                # the destination is resolved now, from the same etc_dir the
                # apply channel will write to: what the operator reads is where
                # the line lands (spec: repair-actions)
                dest = config_edit.destination_label("accept_keywords", line, etc_dir=etc_dir)
                undo = config_edit.undo_text("accept_keywords", line=line, etc_dir=etc_dir)
                specs.append(MenuSpec(
                    key=f"ak-{cpv}",
                    title=f"add '{line}' to {dest} and re-plan",
                    kind="fix",
                    detail=[f"edit: {dest}: {line}", f"undo: {undo}"],
                    action={"type": "package-edit", "kind": "accept_keywords",
                            "lines": [line],
                            "reason": "emerge-ai consent repair (degraded plan)"},
                ))
            elif cand["kind"] == "emaint":
                specs.append(MenuSpec(
                    key="emaint-world",
                    title="repair the world file (emaint --fix world)",
                    kind="fix",
                    tiers=(1,),
                    detail=["a world.emerge-ai.<run-id>.bak copy is created first",
                            "undo: restore that copy over /var/lib/portage/world"],
                    action={"type": "command", "name": "emaint-fix-world", "slots": {}},
                ))
            elif cand["kind"] == "deselect":
                atom = cand.get("atom") or ""
                specs.append(MenuSpec(
                    key=f"deselect-{atom}",
                    title=f"remove {atom} from the world set (emerge --deselect {atom})",
                    kind="fix",
                    tiers=(1,),
                    detail=[f"undo: emerge --noreplace {atom}"],
                    action={"type": "command", "name": "emerge-deselect",
                            "slots": {"atom": atom}},
                ))
        merged_desc = (f"merge the queue as shown ({queue_text}; "
                       f"{len(findings)} finding(s) stay unresolved)")
    else:
        merged_desc = f"merge the queue as shown ({queue_text})"
    specs.append(MenuSpec(key="merge", title=merged_desc, kind="merge", tiers=tiers))
    if len(specs) > MENU_CAP:
        merge = next(s for s in specs if s.kind == "merge")
        fixes = [s for s in specs if s.kind == "fix"]
        specs = fixes[: MENU_CAP - 1] + [merge]
    return specs, manual


def render_question(contract_block: list[str], specs: list[MenuSpec],
                    manual: list[str], note: str = "", stream=None) -> str:
    """Fixed short-line format (design risk): contract, variants, advice.
    `stream` only decides the menu coloring (design D3), echo goes to the
    same stream."""
    variants = [gate.Variant(key=s.key, title=s.title, kind=s.kind, tiers=s.tiers,
                             pros=s.detail)
                for s in specs]
    out = list(contract_block)
    if manual:
        out.append("unresolved findings:")
        out.extend(manual)
    out.append(gate.render(variants, stream=stream))
    if note:
        out.append(ui.warn(note))
    return "\n".join(out)


CONSENT_ANALYSIS_SYSTEM = (
    "You are the installation advisor of emerge-ai (Gentoo). The operator "
    "answered a consent menu with free text — a question, a correction or a "
    "proposal about getting the requested packages installed and the system "
    "updated: that is the whole point of this run. First answer their text "
    "directly and concretely: use the facts in the input and, when they are "
    "not enough, look the answer up with the read-only tools (the plan log "
    "with read_file_window/grep_log, journal_search, check_world, "
    "pretend_emerge hypotheses, web_fetch for upstream). Then, only if the "
    "answer changes which options are useful, order the given variant keys "
    "by usefulness for the operator. You MUST NOT invent actions or rename "
    "keys: the numbered list is fixed by the whitelist. Answer with exactly "
    'one JSON object and nothing else: {"comment": '
    '"<answer to the operator, short lines>", "order": ["<key>", "..."]}.'
)


def build_analysis_messages(specs: list[MenuSpec], operator_text: str,
                            language: str = "English") -> list[dict]:
    """Variant keys/titles and the operator text go through wrap_untrusted
    (spec: prompts): CPVs and typed text originate outside the trust boundary.
    The reply is JSON — the directive pins keys (spec: config-prompts)."""
    menu = injection.wrap_untrusted(
        json.dumps([{"key": s.key, "title": s.title, "kind": s.kind} for s in specs],
                   ensure_ascii=False),
        source="consent-menu")
    text = injection.wrap_untrusted(operator_text, source="operator")
    system = (CONSENT_ANALYSIS_SYSTEM + " "
              + prompts.language_directive(language, structured=True))
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"VARIANTS:\n{menu}\n\nOPERATOR:\n{text}"}]


_KW_RE = re.compile(r"^[\w.+-]+$")


def apply_order(specs: list[MenuSpec], order: list) -> list[MenuSpec]:
    """Stable reorder by known keys only: unknown or duplicate keys drop out
    of the order (the model cannot create a variant), unmentioned keys keep
    their relative place at the end. The merge entry always stays last so a
    mis-sorted menu cannot hide the abort-adjacent position of risky merges."""
    if not isinstance(order, list):
        return specs
    wanted = [k for k in order if isinstance(k, str) and _KW_RE.match(k)]
    by_key = {s.key: s for s in specs}
    picked = [by_key[k] for k in wanted if k in by_key]
    rest = [s for s in specs if s not in picked]
    merged = picked + rest
    merge_specs = [s for s in merged if s.kind == "merge"]
    others = [s for s in merged if s.kind != "merge"]
    return others + merge_specs


def parse_analysis(reply: str) -> tuple[str, list]:
    """Schema {comment, order[]}; any failure degrades to the raw text as the
    comment and an unchanged menu (the dialog never depends on the LLM)."""
    data = llm.try_structured(reply)
    if isinstance(data, dict) and isinstance(data.get("comment"), str):
        order = data.get("order")
        return data["comment"].strip(), order if isinstance(order, list) else []
    return (reply or "").strip(), []


# The channel's read-only tools (change consent-question-channel, D4): the
# agent's whitelist minus ask_operator — the operator is already in the
# dialogue, their text is the question channel. No executing tool exists
# here: a numbered variant stays the only mutation path.
CONSENT_READONLY_TOOLS = (
    "read_file_window", "grep_log", "journal_search",
    "web_fetch", "pretend_emerge", "check_world",
)
CONSENT_TOOL_SPECS = [s for s in agent.TOOL_SPECS
                      if s["function"]["name"] in CONSENT_READONLY_TOOLS]

# issued once when the tool-loop budget runs out mid-round (task 5.1 live
# calibration): the evidence already gathered must produce an answer
TOOL_STOP_DIRECTIVE = (
    "TOOL BUDGET EXHAUSTED — do not call tools any more. Using everything you "
    "have already seen, answer the operator now: exactly one JSON object "
    '{"comment": ..., "order": [...]} and nothing else.'
)


class ConsentDialogue:
    """The stateful model channel behind the consent menu (spec:
    consent-dialogue, change consent-question-channel): the message history
    outlives a round, so the model remembers what it answered and which
    repairs ran, and a follow-up question reads the earlier rounds. Free text
    gets an advisor answer, not a shrug — when the input lacks facts the
    channel inspects the evidence with read-only tools. `analyze(text, specs)
    -> (comment, order)` keeps the run_dialog seam signature; ANY round
    failure degrades to a note above the menu (the unguarded dict-shaped
    read of a Response is what once killed a live run)."""

    HISTORY_BUDGET = 24_000  # serialized chars before compression kicks in

    def __init__(self, client, *, language: str = "English", sandbox=None,
                 max_rounds: int = 6, repairs: list | None = None):
        self.client = client
        self.language = language
        # sandbox None keeps the channel tool-free (tests, jail-less hosts)
        self.sandbox = sandbox
        self.max_rounds = max_rounds
        # the live run.consent_repairs list: the history digest names the
        # fixes applied through the menu since the run began
        self.repairs = repairs if repairs is not None else []
        # one entry per round: [user, assistant/tool exchange..., assistant]
        self.rounds: list[list[dict]] = []

    def analyze(self, text, specs):
        try:
            return self._round(text, specs)
        except Exception as exc:  # the menu, not the run, absorbs a bad round
            return f"consent analysis unavailable ({exc})", []

    def _round(self, text, specs):
        pair = build_analysis_messages(specs, text, language=self.language)
        current: list[dict] = [pair[1]]
        request = self._request(pair[0], current)
        if self.sandbox is not None and CONSENT_TOOL_SPECS:
            recorded: list[dict] = []
            try:
                resp = llm.run_tool_loop(self.client, request, CONSENT_TOOL_SPECS,
                                         self._dispatch(), max_rounds=self.max_rounds,
                                         record=recorded)
            except llm.LimitExhausted:
                # the live check (task 5.1): an endpoint that spends the whole
                # budget is working productively, not stuck — throw away the
                # budget, not the collected evidence: one tool-free round
                # forces the conclusion. A failure here degrades to a note.
                current.extend(recorded)
                current.append({"role": "user", "content": TOOL_STOP_DIRECTIVE})
                resp = self.client.chat(request + recorded + [current[-1]])
            else:
                current.extend(recorded)
        else:
            resp = self.client.chat(request)
        reply = llm.response_text(resp)
        current.append({"role": "assistant", "content": reply})
        self.rounds.append(current)
        return parse_analysis(reply)

    def _request(self, system_msg: dict, current: list[dict]) -> list[dict]:
        flat = [m for r in self.rounds for m in r] + current
        size = sum(len(json.dumps(m, ensure_ascii=False)) for m in flat)
        if size <= self.HISTORY_BUDGET or len(self.rounds) <= 2:
            return [system_msg] + flat
        # deterministic compression (design D2): every round but the last two
        # folds into one system digest — no LLM summarising, cheap to audit
        digest = {"role": "system", "content": self._digest(self.rounds[:-2])}
        return ([system_msg, digest]
                + [m for r in self.rounds[-2:] for m in r] + current)

    def _digest(self, collapsed: list[list[dict]]) -> str:
        def plain(text: str, cap: int) -> str:
            body = [ln for ln in text.splitlines() if not ln.startswith("<<<")]
            return " ".join(" ".join(body).split())[:cap]

        lines = ["EARLIER CONSENT ROUNDS (condensed; the recent ones follow "
                 "verbatim):"]
        for rnd in collapsed:
            asked = rnd[0]["content"].rpartition("OPERATOR:")[2]
            lines.append("  - operator: " + plain(asked, 120))
            answered = next((m.get("content") for m in reversed(rnd)
                             if m["role"] == "assistant" and m.get("content")), "")
            if answered:
                lines.append("    answered: " + plain(answered, 160))
        if self.repairs:
            lines.append("  - repairs applied from this menu: "
                         + ", ".join(str(r.get("variant", "?")) for r in self.repairs))
        return "\n".join(lines)

    def _dispatch(self):
        """The same read-only executors as the incident agent, without its
        interactive gating (design D4): dispatched straight off the Sandbox
        methods; jail and caps are the sandbox's."""
        sandbox = self.sandbox

        def call(name: str, args: dict) -> dict:
            # progress-logging: the round must show what it is doing, the
            # same capped activity line the incident agent prints
            print(ui.activity(f"tool: {name}("
                              f"{ui.clip(json.dumps(args, ensure_ascii=False), 160)})"),
                  file=sys.stderr)
            try:
                if name == "read_file_window":
                    out = sandbox.read_file_window(
                        args.get("path", ""), int(args.get("offset", 0)),
                        int(args.get("limit", 200)))
                elif name == "grep_log":
                    out = sandbox.grep_log(args.get("path", ""), args.get("pattern", ""))
                elif name == "journal_search":
                    out = sandbox.journal_search(*[str(a) for a in args.get("args", [])])
                elif name == "web_fetch":
                    out = sandbox.web_fetch(args.get("url", ""))
                elif name == "pretend_emerge":
                    out = sandbox.pretend_emerge(
                        list(args.get("atoms", [])), list(args.get("extra_flags", [])),
                        dict(args.get("env_overrides", {}) or {}))
                elif name == "check_world":
                    out = sandbox.check_world()
                else:
                    return {"error": f"unknown tool {name}"}
            except PermissionError as exc:
                return {"error": f"denied by sandbox: {exc}"}
            data = json.dumps(out, ensure_ascii=False)
            if name in ("read_file_window", "grep_log", "web_fetch", "check_world"):
                data = injection.wrap_untrusted(data, source=name)
            return {"content": data[:agent.MAX_TOOL_RESULT_CHARS]}

        return call


def run_dialog(specs: list[MenuSpec], *, contract_block: list[str], manual: list[str],
               mode: dict, audit_path, echo=print, input_fn=None,
               analyze=None, execute=None, confirm_required: bool = False,
               stream=None) -> dict:
    """The consent loop (no round counter by design D5): number -> gate core;
    y/n -> legacy equivalence (merge as-is / abort, design D7); free text ->
    model channel -> menu again; EOF/quit -> 'no answer', zero mutations.
    `execute(spec)` runs the typed action right after the audit line through
    the gate core — the single mutation point stays in gate.apply_variant.
    Returns {'status': abort|merge|applied|denied|declined|empty, ...}."""
    if not any(s.kind in ("merge", "fix") for s in specs):
        return {"status": "empty"}
    note = ""
    while True:
        echo(render_question(contract_block, specs, manual, note, stream=stream))
        note = ""
        raw = None
        try:
            # bare input(): resolved at call time so patched test input works
            raw = (input_fn or input)(ui.prompt("Your choice [number/y/N] (q = abort): "))
        except (EOFError, KeyboardInterrupt):
            # ctrl-c is a guaranteed exit of every round (spec: exits)
            return {"status": "abort", "reason": "interrupted; nothing changed"}
        text = (raw or "").strip()
        low = text.lower()
        if low in ("", "q", "quit", "abort", "n", "no"):
            return {"status": "abort", "reason": "operator aborted; nothing changed"}
        sel: MenuSpec | None = None
        if low in ("y", "yes"):
            sel = next((s for s in specs if s.kind == "merge"), None)
            if sel is None:
                note = "there is no merge to confirm (empty queue) — pick a fix or q"
                continue
        elif text.isdigit() and 1 <= int(text) <= len(specs):
            sel = specs[int(text) - 1]
        if sel is None:
            if analyze is None:
                note = "LLM analysis unavailable — pick a number, y or q"
                continue
            comment, order = analyze(text, specs)
            if comment:
                echo(comment)
            specs = apply_order(specs, order)
            continue
        if sel.kind == "merge":
            return {"status": "merge", "variant": sel.key}
        decision = gate.apply_variant(
            gate.Variant(key=sel.key, title=sel.title, kind=sel.kind, tiers=sel.tiers,
                         pros=sel.detail,
                         action=(lambda s=sel: execute(s)) if execute else (lambda: None)),
            mode=mode, audit_path=audit_path, echo=echo,
            confirm_required=confirm_required)
        if decision.get("status") != "applied":
            # denied/declined: the matrix said no to THIS variant — the dialog
            # goes on; the operator, not a counter, ends it (design D5)
            note = decision.get("reason") or f"[{sel.key}] not applied"
            continue
        decision["spec"] = sel  # the caller re-reads the action for the re-resolve
        return decision
