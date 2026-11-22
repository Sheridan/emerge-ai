"""Runtime version compatibility check (spec: cli-compat / Привязка версии к portage)."""

from __future__ import annotations

from dataclasses import dataclass


def _parse(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.split(".")[:2]:
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@dataclass
class CompatResult:
    ok: bool
    message: str


def check_version_compat(portage_version: str, app_version: str) -> CompatResult:
    """Portage major.minor must equal the project major.minor (3.0.*.* <-> 3.0)."""
    try:
        p = _parse(portage_version)
        a = _parse(app_version)
    except ValueError as exc:
        return CompatResult(False, f"emerge-ai: cannot parse versions: {exc}")
    if p != a:
        return CompatResult(
            False,
            f"emerge-ai {app_version} is incompatible with Portage {portage_version}: "
            f"python-API compatibility boundary is major.minor ({a[0]}.{a[1]}). "
            f"Install the emerge-ai release matching Portage {p[0]}.{p[1]}.x or use plain emerge.",
        )
    return CompatResult(True, f"emerge-ai {app_version} compatible with Portage {portage_version}")
