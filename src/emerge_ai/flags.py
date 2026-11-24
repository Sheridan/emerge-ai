"""Own-flag parsing layered on top of emerge's argv (spec: cli-compat)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Mode:
    noninteractive: bool = False
    responsibility: bool = False
    changelog: bool = False
    rollback: bool = False


@dataclass(frozen=True)
class _OwnFlagDef:
    flag: str
    mode_field: str
    description: str
    alias: str | None = None


_OWN_FLAG_DEFS = (
    _OwnFlagDef(
        "--noninteractive",
        "noninteractive",
        "no TTY questions; autonomy matrix decides, fail-closed otherwise",
    ),
    _OwnFlagDef(
        "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences",
        "responsibility",
        "full autonomy including rollback execution",
        alias="--i-understand-the-risks",
    ),
    _OwnFlagDef(
        "--changelog",
        "changelog",
        "changelog digest (news/GLESA/GitHub/git) instead of emerging",
    ),
    _OwnFlagDef(
        "--rollback",
        "rollback",
        "recovery mode: list recovery points, restore one after confirmation; "
        "emerge is never started (noninteractive needs the responsibility flag)",
    ),
)

# Single source of truth: own flag -> name of the Mode field it sets.
# Aliases set the same field as their canonical flag.
OWN_FLAGS: dict[str, str] = {}
for _d in _OWN_FLAG_DEFS:
    OWN_FLAGS[_d.flag] = _d.mode_field
    if _d.alias:
        OWN_FLAGS[_d.alias] = _d.mode_field


def _build_own_flag_help() -> str:
    desc_col = 22
    lines = ["emerge-ai own flags (everything else is passed to emerge verbatim):"]
    for d in _OWN_FLAG_DEFS:
        shown = d.flag + (f" (or {d.alias})" if d.alias else "")
        if len(shown) + 2 <= desc_col - 2:
            lines.append(f"  {shown:<{desc_col - 2}}{d.description}")
        else:
            lines.append(f"  {shown}")
            lines.append(f"  {'':<{desc_col - 2}}{d.description}")
    lines.append("")
    return "\n".join(lines)


OWN_FLAG_HELP = _build_own_flag_help()


def parse_own_flags(argv: list[str]) -> tuple[Mode, list[str]]:
    """Strip emerge-ai's own flags (exact match, any position); the rest is emerge's."""
    mode = Mode()
    rest: list[str] = []
    for arg in argv:
        mode_field = OWN_FLAGS.get(arg)
        if mode_field is None:
            rest.append(arg)
        else:
            setattr(mode, mode_field, True)
    return mode, rest
