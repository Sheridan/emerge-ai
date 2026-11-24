"""Pretend-phase enrichment: genlop estimates + short plan digest (spec: run-reporting)."""

from __future__ import annotations

import json
import re
import subprocess
import sys

from emerge_ai import injection, prompts, ui

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MERGE_TIME = re.compile(
    r"merge time:\s*(?:(\d+)\s*hours?)?\s*(?:(\d+)\s*minutes?)?\s*(?:(\d+)\s*seconds?)?"
)

PLAN_SUMMARY_SYSTEM = (
    "You are the plan briefer of emerge-ai (Gentoo). From the deterministic plan digest "
    "and the package/tier list below, write 2-5 short plain-text lines on what matters in "
    "this upcoming merge (high-tier or unusual packages, notable USE changes if present). "
    "Use ONLY facts in the input: never invent numbers, durations, tiers or flags, and "
    "never assert anything absent from the input. " + prompts.PLAIN_TEXT_DIRECTIVE
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


def build_plan_summary_messages(plan, core_text: str) -> list[dict]:
    """Prompt for the LLM plan summary. CPVs come from foreign ebuilds, so the
    core digest and the package list go through wrap_untrusted (spec: prompts)."""
    entries = [{"cpv": e.cpv, "tier": e.tier} for e in plan.entries]
    user = (
        "DIGEST:\n" + injection.wrap_untrusted(core_text, source="digest")
        + "\n\nPACKAGES:\n" + injection.wrap_untrusted(json.dumps(entries), source="plan")
    )
    return [{"role": "system", "content": PLAN_SUMMARY_SYSTEM},
            {"role": "user", "content": user}]


def plan_digest(plan, estimate=genlop_estimate, stream=None, summarize=None) -> str:
    """Short human digest shown after emerge's own pretend output. Tier lines get
    the fixed risk gradient when the stream is a color TTY (design D2).

    `summarize` (optional) is an LLM seam taking the summary messages and
    returning text: its answer is appended after the deterministic core, which
    stays byte-identical. Any seam failure degrades silently to the core
    (enrichment must never break emerge's own flow)."""
    stream = sys.stdout if stream is None else stream
    dist = plan.distribution
    lines = ["emerge-ai plan digest:"]
    for tier in sorted(dist):
        names = ", ".join(e.cpv for e in plan.entries if e.tier == tier)
        line = f"  tier {tier}: {dist[tier]} pkg(s) — {names}"
        lines.append(ui.paint(stream, ui.color_sgr(ui.TIER_GRADIENT.get(tier)), line))
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
    if summarize is not None:
        core = "\n".join(ANSI.sub("", line) for line in lines)
        try:
            reply = summarize(build_plan_summary_messages(plan, core))
            reply = ANSI.sub("", str(getattr(reply, "content", reply) or "")).strip()
        except Exception:  # design D3: no LLM (or a broken one) -> core only
            reply = ""
        if reply:
            pal = ui.resolve_palette(None)
            lines.append(ui.paint(stream, ui.color_sgr(pal["content"]), "  llm summary:"))
            for rl in reply.splitlines():
                lines.append(ui.paint(stream, ui.color_sgr(pal["content"]), f"  {rl}"))
    return "\n".join(lines)
