"""CLI entry point (full flag matrix in groups 2+)."""

from __future__ import annotations

import sys

from emerge_ai import __version__
from emerge_ai.compat import check_version_compat
from emerge_ai.portage_compat import PortageUnavailable, portage_version


def _portage_version_or_exit() -> str:
    try:
        return portage_version()
    except PortageUnavailable as exc:
        print(f"emerge-ai: {exc}", file=sys.stderr)
        raise SystemExit(3)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-V"):
        pv = _portage_version_or_exit()
        print(f"emerge-ai {__version__}")
        print(f"Portage {pv}")
        return 0

    parser_error = (
        "emerge-ai: no command selected (pass emerge-compatible arguments; "
        "see --help)\n"
    )
    print(parser_error, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
