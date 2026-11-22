"""Consent gate + autonomy matrix + apply channel (spec: consent-autonomy).

apply_variant() is the ONLY place mutations may happen; every decision is
audited before execution.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

AUDIT_PATH = "/var/log/emerge-ai/decisions.log"

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


def render(variants: list[Variant]) -> str:
    lines = []
    for i, v in enumerate(variants, 1):
        lines.append(f"[{i}] {v.title}  ({v.kind})")
        for p in v.pros:
            lines.append(f"      + {p}")
        for c in v.cons:
            lines.append(f"      - {c}")
        for r in v.risks:
            lines.append(f"      ! risk: {r}")
    lines.append("[c] propose your own text   [q] quit (no changes)")
    return "\n".join(lines)


def autonomy_decision(mode: dict, variant: Variant) -> tuple[str, str]:
    """mode flags -> AUTO/ASK/DENY + human-readable justification (shown in all
    cases; responsibility mode is the only fully autonomous one)."""
    if mode.get("responsibility"):
        return AUTO, (
            "--i-understand-the-risks: autonomous apply at all tiers "
            f"(queue tiers {variant.tiers or (5,)}, kind={variant.kind}); "
            "recovery point verification still required before mutations"
        )
    if variant.kind == "rollback":
        # rollbacks always need an explicit human unless responsibility
        return DENY if mode.get("noninteractive") else ASK, (
            "rollback requires explicit human confirmation "
            "(--i-understand-the-risks to automate)"
        )
    if mode.get("noninteractive"):
        if variant.tiers and max(variant.tiers) == 5 and variant.kind == "fix":
            return AUTO, "--noninteractive: rest-tier auto-repair allowed"
        return DENY, (
            f"--noninteractive: refusing auto-{variant.kind} at tiers {variant.tiers}; "
            "run interactively or pass --i-understand-the-risks"
        )
    return ASK, "default mode: every mutation requires a human yes"


def audit(entry: dict, path: str | Path = AUDIT_PATH) -> None:
    entry = {"ts": time.time(), **entry}
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # audit must never mask the gate decision


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
    confirmation, autonomy matrix, audit. Returns a decision dict."""
    last_error = ""
    while True:
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
        verdict, reason = autonomy_decision(mode, variant)
        echo(f"emerge-ai: autonomy: {reason}")
        if verdict == DENY:
            audit({"mode": mode, "variant": variant.key, "decision": "denied", "reason": reason},
                  audit_path)
            return {"status": "denied", "variant": variant.key, "reason": reason, "exit": 6}
        if verdict == ASK:
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
