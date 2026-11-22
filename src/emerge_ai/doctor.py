"""Auto-doctor for world/system/mass updates (spec: cli-compat / doctor)."""

from __future__ import annotations

from emerge_ai.enrich import format_duration, genlop_estimate

MASSIVE_ARGV = ("@world", "@system")
WARNING_TIERS = (1, 2, 3)


def is_mass_update(emerge_args: list[str], plan=None, threshold: int = 50) -> bool:
    if any(a.startswith("@") for a in emerge_args):
        return True
    return plan is not None and len(plan.entries) >= threshold


def doctor_report(plan, estimate=genlop_estimate) -> list[str]:
    """Warnings for the plan; silent ([]) when everything is rest-tier."""
    warnings = [
        f"  tier {e.tier}: {e.cpv} — critical subsystem, changes can break boot/login/network"
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
