"""Pretend-phase enrichment: genlop estimates + short plan digest (spec: run-reporting)."""

from __future__ import annotations

import re
import subprocess

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MERGE_TIME = re.compile(
    r"merge time:\s*(?:(\d+)\s*hours?)?\s*(?:(\d+)\s*minutes?)?\s*(?:(\d+)\s*seconds?)?"
)


def parse_genlop(text: str) -> int | None:
    """Seconds of the most recent recorded merge time in genlop output."""
    clean = ANSI.sub("", text)
    matches = MERGE_TIME.findall(clean)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(seconds or 0)


def genlop_estimate(cpv_or_atom: str) -> int | None:
    try:
        proc = subprocess.run(
            ["genlop", "-t", cpv_or_atom], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_genlop(proc.stdout)


def format_duration(seconds: int) -> str:
    parts = []
    for value, unit in ((seconds // 3600, "h"), (seconds % 3600 // 60, "min"), (seconds % 60, "s")):
        if value:
            parts.append(f"{value}{unit}")
    return " ".join(parts) or "0s"


def plan_digest(plan, estimate=genlop_estimate) -> str:
    """Short human digest shown after emerge's own pretend output."""
    dist = plan.distribution
    lines = ["emerge-ai plan digest:"]
    for tier in sorted(dist):
        names = ", ".join(e.cpv for e in plan.entries if e.tier == tier)
        lines.append(f"  tier {tier}: {dist[tier]} pkg(s) — {names}")
    total = 0
    unknown = 0
    for entry in plan.entries:
        secs = estimate(entry.cpv) if estimate else None
        if secs is None:
            unknown += 1
        else:
            total += secs
    est = format_duration(total)
    lines.append(
        f"  build time estimate: {est}"
        + (f" (+{unknown} without genlop data)" if unknown else "")
    )
    if unknown:
        lines.append("  note: packages without data above are unmeasured, treat estimate as lower bound")
    return "\n".join(lines)
