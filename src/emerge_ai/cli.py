"""CLI entry point: own flags, compat gate, emerge passthrough, -a/-p interception."""

from __future__ import annotations

import sys

from emerge_ai import hooks, portage_compat
from emerge_ai import __version__
from emerge_ai.compat import check_version_compat
from emerge_ai.flags import OWN_FLAGS, OWN_FLAG_HELP, Mode, parse_own_flags
from emerge_ai.runner import (
    confirm,
    drop_flags,
    run_emerge,
    run_emerge_capturing,
)

PRETEND_FLAGS = ("-p", "--pretend")
ASK_FLAGS = ("-a", "--ask")


def _version_text() -> tuple[str, int]:
    try:
        pv = portage_compat.portage_version()
    except portage_compat.PortageUnavailable as exc:
        return f"emerge-ai {__version__}\nPortage: unavailable ({exc})\n", 3
    return f"emerge-ai {__version__}\nPortage {pv}\n", 0


def _compat_gate() -> int | None:
    """Return exit code when incompatible, None when OK to touch emerge."""
    try:
        pv = portage_compat.portage_version()
    except portage_compat.PortageUnavailable as exc:
        print(f"emerge-ai: {exc}", file=sys.stderr)
        return 3
    result = check_version_compat(pv, __version__)
    if not result.ok:
        print(f"emerge-ai: {result.message}", file=sys.stderr)
        return 4
    return None


def main(argv: list[str] | None = None, emerge_binary: str = "emerge") -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-V"):
        text, code = _version_text()
        print(text, end="")
        return code

    if argv and argv[0] == "--help":
        print(OWN_FLAG_HELP)
        print("Run 'emerge-ai -h' (or any emerge option) for emerge's own help.")
        return 0

    mode, emerge_args = parse_own_flags(argv)

    blocked = _compat_gate()
    if blocked is not None:
        return blocked

    pretend = any(a in PRETEND_FLAGS for a in emerge_args)
    ask = any(a in ASK_FLAGS for a in emerge_args)

    if not pretend and not ask:
        return run_emerge(emerge_args, emerge_binary=emerge_binary)

    plan_args = list(emerge_args)
    if ask and not pretend:
        plan_args.append("--pretend")
    rc, output = run_emerge_capturing(plan_args, emerge_binary=emerge_binary)
    if rc != 0:
        return rc

    hooks.run_hook(output, mode)

    if ask:
        if mode.noninteractive:
            if not mode.responsibility:
                print(
                    "emerge-ai: --noninteractive without responsibility flag: proceeding "
                    "(plan contains only rest-tier work; tiers gate applies at merge)",
                    file=sys.stderr,
                )
        elif not confirm():
            print("emerge-ai: aborted by user.", file=sys.stderr)
            return 0
        merge_args = drop_flags(emerge_args, ASK_FLAGS + PRETEND_FLAGS)
        return run_emerge(merge_args, emerge_binary=emerge_binary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
