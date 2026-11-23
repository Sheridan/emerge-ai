"""Auto-doctor for world/system/mass updates (spec: cli-compat / doctor)."""

from __future__ import annotations

import sys

from emerge_ai import ui
from emerge_ai.enrich import format_duration, genlop_estimate

MASSIVE_ARGV = ("@world", "@system")
WARNING_TIERS = (1, 2, 3)


def is_mass_update(emerge_args: list[str], plan=None, threshold: int = 50) -> bool:
    if any(a.startswith("@") for a in emerge_args):
        return True
    return plan is not None and len(plan.entries) >= threshold


def doctor_report(plan, estimate=genlop_estimate, stream=None) -> list[str]:
    """Warnings for the plan; silent ([]) when everything is rest-tier.
    Warning lines share the plan-digest tier gradient on color TTYs."""
    stream = sys.stderr if stream is None else stream
    warnings = [
        ui.paint(
            stream,
            ui.color_sgr(ui.TIER_GRADIENT.get(e.tier)),
            f"  tier {e.tier}: {e.cpv} — critical subsystem, changes can break boot/login/network",
        )
        for e in plan.entries
        if e.tier in WARNING_TIERS
    ]
    if not warnings:
        return []
    total = 0
    for entry in plan.entries:
        secs = estimate(entry.cpv) if estimate else None
        if secs:
            total += secs
    header = [
        f"emerge-ai doctor: {len(warnings)} package(s) tier<=3 in queue "
        f"(total estimate ~{format_duration(total)}):"
    ]
    return header + warnings
