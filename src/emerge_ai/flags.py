"""Own-flag parsing layered on top of emerge's argv (spec: cli-compat)."""

from __future__ import annotations

from dataclasses import dataclass, field

OWN_FLAGS = ("--noninteractive", "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences", "--changelog")
OWN_FLAG_HELP = """emerge-ai own flags (everything else is passed to emerge verbatim):
  --noninteractive    no TTY questions; autonomy matrix decides, fail-closed otherwise
  --i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences
                      full autonomy including rollback execution
  --changelog           changelog digest (news/GLESA/GitHub/git) instead of emerging
"""


@dataclass
class Mode:
    noninteractive: bool = False
    responsibility: bool = False
    changelog: bool = False


def parse_own_flags(argv: list[str]) -> tuple[Mode, list[str]]:
    """Strip emerge-ai's own flags from argv; the rest belongs to emerge."""
    mode = Mode()
    rest: list[str] = []
    for arg in argv:
        if arg == "--noninteractive":
            mode.noninteractive = True
        elif arg == OWN_FLAGS[1]:
            mode.responsibility = True
        elif arg == OWN_FLAGS[2]:
            mode.changelog = True
        else:
            rest.append(arg)
    return mode, rest
