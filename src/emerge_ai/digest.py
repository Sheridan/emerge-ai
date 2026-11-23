"""Post-run digest (spec: digest-changelog): built/installed packages plus the
agent's actions, printed when the config option is on."""

from __future__ import annotations

import re

EBUILD_LINE_RE = re.compile(r"^\[ebuild\s+[NnUuRrFf]*\s*\]\s+(\S+)", re.M)
MERGE_HEAD_RE = re.compile(r"^>>> Emerging \(.*?\) (\S+)", re.M)


def parse_installed(text: str) -> list[str]:
    out: list[str] = []
    for rx in (MERGE_HEAD_RE, EBUILD_LINE_RE):
        for m in rx.finditer(text):
            cpv = m.group(1)
            if cpv not in out:
                out.append(cpv)
    return out


def post_run_digest(run, emerge_output: str) -> str:
    cpvs = parse_installed(emerge_output)
    lines = ["emerge-ai: run digest:"]
    lines.append("  built/installed: " + (", ".join(cpvs) if cpvs else "nothing (already current?)"))
    actions: list[str] = []
    if getattr(run, "incident", None):
        actions.append(f"incident {run.incident.get('class')} was analysed")
    proposal = getattr(run, "agent_proposal", None)
    if proposal:
        first = next((l for l in proposal.splitlines() if l.strip()), "")
        actions.append(f"agent proposed: {first[:160]}")
    prot = getattr(run, "protection", None) or {}
    if prot.get("snapshot") or prot.get("archive"):
        actions.append("recovery point created and cleaned up after success")
    lines.append("  agent actions: " + ("; ".join(actions) if actions else "none"))
    return "\n".join(lines)
