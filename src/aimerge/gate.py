"""Consent gate + autonomy matrix + apply channel (spec: consent-autonomy).

apply_variant() is the ONLY place mutations may happen; every decision is
audited before execution.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aimerge import ui

AUDIT_PATH = "/var/log/aimerge/decisions.log"

AUTO = "auto"
ASK = "ask"
DENY = "deny"


@dataclass
class Variant:
    key: str
    title: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)  # each mentions tier, e.g. "kernel tier 1"
    kind: str = "fix"  # fix | rollback | investigate
    action: Callable[[], object] = lambda: None
    tiers: tuple[int, ...] = (5,)


def render(variants: list[Variant], *, stream=None) -> str:
    """The numbered variant menu as a highlighted decision block
    (spec: console-output): blank line, bold-yellow banner, green [N],
    yellow body, closing blank line. `stream` only decides coloring —
    callers echo the returned string to that same stream (design D3);
    pipes, NO_COLOR and TERM=dumb get the exact same text without codes."""
    stream = sys.stdout if stream is None else stream
    lines = ["", ui.decision_banner_line(stream)]
    for i, v in enumerate(variants, 1):
        lines.append(ui.decision_choice(stream, f"[{i}]", f" {v.title}  ({v.kind})"))
        for p in v.pros:
            lines.append(ui.decision_text(stream, f"      + {p}"))
        for c in v.cons:
            lines.append(ui.decision_text(stream, f"      - {c}"))
        for r in v.risks:
            lines.append(ui.decision_text(stream, f"      ! risk: {r}"))
    lines.append(ui.decision_text(
        stream, "[c] propose your own text   [q] quit (no changes)"))
    lines.append("")
    return "\n".join(lines)


def autonomy_decision(mode: dict, variant: Variant) -> tuple[str, str]:
    """mode flags -> AUTO/ASK/DENY + human-readable justification (shown in all
    cases; responsibility mode is the only fully autonomous one)."""
    if mode.get("responsibility"):
        return AUTO, (
            "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences:"
            f" autonomous apply at all tiers "
            f"(queue tiers {variant.tiers or (5,)}, kind={variant.kind}); "
            "recovery point verification still required before mutations"
        )
    if variant.kind == "rollback":
        # rollbacks always need an explicit human unless responsibility
        return DENY if mode.get("noninteractive") else ASK, (
            "rollback requires explicit human confirmation "
            "(--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences"
            " to automate)"
        )
    if mode.get("noninteractive"):
        if variant.tiers and max(variant.tiers) == 5 and variant.kind in ("fix", "merge"):
            # "merge": the CLI's own mutation gate reuses this matrix (D1 of
            # wire-autonomy-gate); rest-tier queues are as safe as rest-tier fixes
            what = "merge" if variant.kind == "merge" else "auto-repair"
            return AUTO, f"--noninteractive: rest-tier {what} allowed"
        return DENY, (
            f"--noninteractive: refusing auto-{variant.kind} at tiers {variant.tiers}; "
            "run interactively or pass "
            "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences"
        )
    return ASK, "default mode: every mutation requires a human yes"


def audit(entry: dict, path: str | Path = AUDIT_PATH) -> bool:
    """Append one decision line; True when the line definitely hit disk.
    Callers may fail-close on False (the seam must never mutate unrecorded)."""
    entry = {"ts": time.time(), **entry}
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False  # audit must never mask the gate decision itself


def apply_variant(
    variant: Variant,
    *,
    mode: dict,
    confirm_fn: Callable[[str], bool] = lambda prompt: False,
    audit_path: str | Path = AUDIT_PATH,
    echo=print,
    confirm_required: bool = True,
) -> dict:
    """The execution core (single mutation point): autonomy matrix -> audit ->
    action. Explicit menu choice elsewhere may skip the extra confirm (the
    selection itself is the consent, spec: consent-dialogue D1); the audit
    line is written either way. gate() and the consent dialog share this."""
    verdict, reason = autonomy_decision(mode, variant)
    echo(f"aimerge: autonomy: {reason}")
    if verdict == DENY:
        audit({"mode": mode, "variant": variant.key, "decision": "denied", "reason": reason},
              audit_path)
        return {"status": "denied", "variant": variant.key, "reason": reason, "exit": 6}
    if verdict == ASK and confirm_required:
        if not confirm_fn(f"Apply variant [{variant.key}] {variant.title}? [y/N] "):
            audit({"mode": mode, "variant": variant.key, "decision": "declined"}, audit_path)
            return {"status": "declined", "variant": variant.key}
    audit(
        {"mode": mode, "variant": variant.key, "kind": variant.kind, "decision": "apply",
         "autonomy": verdict, "reason": reason},
        audit_path,
    )
    variant.action()
    return {"status": "applied", "variant": variant.key, "autonomy": verdict}


def gate(
    variants: list[Variant],
    *,
    mode: dict,
    confirm_fn: Callable[[str], bool],
    input_fn: Callable[[str], str] = input,
    effects_fn: Callable[[str], str] = lambda text: f"effects of custom plan are not analysable: {text!r}",
    audit_path: str | Path = AUDIT_PATH,
    echo=print,
) -> dict:
    """Numbered choice, own-text -> consequences -> re-ask loop, explicit final
    confirmation, autonomy matrix, audit. Returns a decision dict.
    A bounded number of rounds: a stdin that keeps answering junk (scripted
    pipe, not a present operator) quits instead of spinning forever."""
    last_error = ""
    rounds = 0
    while True:
        rounds += 1
        if rounds > 6:
            audit({"mode": mode, "decision": "quit", "reason": "too many rounds"}, audit_path)
            return {"status": "quit", "reason": "too many invalid rounds; treating operator as absent"}
        if last_error:
            echo(last_error)
        echo(render(variants))
        try:
            answer = input_fn("Choose variant [number/c/q]: ").strip().lower()
        except EOFError:
            answer = "q"
        if answer in ("q", "quit", ""):
            audit({"mode": mode, "decision": "quit"}, audit_path)
            return {"status": "quit", "reason": "operator quit without changes"}
        if answer == "c":
            try:
                text = input_fn("Your text: ")
            except EOFError:
                continue
            echo(effects_fn(text))
            last_error = "(own text is not executable; pick a concrete variant)"
            continue
        if not answer.isdigit() or not 1 <= int(answer) <= len(variants):
            last_error = f"invalid choice {answer!r}"
            continue
        variant = variants[int(answer) - 1]
        return apply_variant(variant, mode=mode, confirm_fn=confirm_fn,
                             audit_path=audit_path, echo=echo)
