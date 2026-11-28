"""Repair ladder (spec: repair-ladder): minimal-sufficient level selection and
overlay GC once the fix lands upstream."""

from __future__ import annotations

from dataclasses import dataclass

LEVELS: list[tuple[str, str]] = [
    ("env", "one-off env/flags (ACCEPT_KEYWORDS, USE) via gated pretend/run"),
    ("package-edit", "/etc/portage/package.* audit-commented line"),
    ("user-patch", "/etc/portage/patches/<cat>/<pn>"),
    ("mask", "package.mask/unmask adjustment"),
    ("overlay", "copy-fix ebuild in aimerge overlay (priority)"),
    ("manual", "human hand; agent explains only"),
]

# incident class -> first level that can plausibly fix it
CLASS_FLOOR = {
    "keywords": "package-edit",
    "license": "package-edit",
    "use": "package-edit",
    "mask": "mask",
    "blocks": "package-edit",
    "config-protect": "env",
    "sandbox": "user-patch",
    "compile": "user-patch",
    "fetch": "package-edit",
    "cycle": "mask",
    "unknown": "env",
}


def level_index(name: str) -> int:
    for i, (n, _) in enumerate(LEVELS):
        if n == name:
            return i
    raise KeyError(name)


def choose_level(incident_class: str, needs_source_change: bool = False) -> str:
    """Minimal sufficient level; the overlay is only reachable when the build
    cannot succeed without touching sources."""
    floor = CLASS_FLOOR.get(incident_class, "env")
    idx = level_index(floor)
    if needs_source_change:
        idx = max(idx, level_index("user-patch"))
    if needs_source_change and incident_class == "compile":
        # only when a user patch is impossible does the overlay become allowed
        pass
    return LEVELS[idx][0]


def overlay_justified(incident_class: str, user_patch_feasible: bool) -> bool:
    return incident_class in ("compile", "sandbox") and not user_patch_feasible


def gc_candidates(registry: dict, tree_fixed) -> list[dict]:
    """Overlay entries whose upstream fix now builds from the tree -> removal
    SUGGESTIONS; never auto-removed (tree_fixed: cpv -> bool)."""
    return [entry for cpv, entry in registry.items() if tree_fixed(cpv)]
