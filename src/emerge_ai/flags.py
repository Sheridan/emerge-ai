"""Own-flag parsing layered on top of emerge's argv (spec: cli-compat)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Mode:
    noninteractive: bool = False
    responsibility: bool = False
    changelog: bool = False


@dataclass(frozen=True)
class _OwnFlagDef:
    flag: str
    mode_field: str
    description: str


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
    ),
    _OwnFlagDef(
        "--changelog",
        "changelog",
        "changelog digest (news/GLESA/GitHub/git) instead of emerging",
    ),
)

# Single source of truth: own flag -> name of the Mode field it sets.
OWN_FLAGS: dict[str, str] = {d.flag: d.mode_field for d in _OWN_FLAG_DEFS}


def _build_own_flag_help() -> str:
    desc_col = 22
    lines = ["emerge-ai own flags (everything else is passed to emerge verbatim):"]
    for d in _OWN_FLAG_DEFS:
        if len(d.flag) + 2 <= desc_col - 2:
            lines.append(f"  {d.flag:<{desc_col - 2}}{d.description}")
        else:
            lines.append(f"  {d.flag}")
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
