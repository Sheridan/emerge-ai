"""Subprocess execution of emerge (design D1: emerge itself is never replaced)."""

from __future__ import annotations

import os
import subprocess
import sys

from emerge_ai import ui

EMERGE = "emerge"


def run_emerge(emerge_args: list[str], emerge_binary: str = EMERGE) -> int:
    """Passthrough: inherited stdio, emerge's exit code returned verbatim."""
    return subprocess.run([emerge_binary, *emerge_args]).returncode


def run_emerge_capturing(emerge_args: list[str], emerge_binary: str = EMERGE) -> tuple[int, str]:
    """Run emerge (typically --pretend), mirroring output to stdout while
    buffering it for the enrichment hook. No TTY is attached. stdout stays
    byte-identical passthrough (spec: console-output); the buffer is ANSI-stripped
    because it feeds parsing and the LLM (design D5)."""
    proc = subprocess.Popen(
        [emerge_binary, *emerge_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(ui.strip_ansi(line))
    proc.wait()
    return proc.returncode, "".join(lines)


def confirm(prompt: str = "Proceed? [y/N] ", stream=sys.stdin) -> bool:
    """Final consent gate owned by emerge-ai; EOF counts as 'no'."""
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _flag_kinds(flags: tuple[str, ...]) -> tuple[set[str], set[str]]:
    """Split flag specs into two kinds:

    longs  - whole long options to match exactly ("--ask");
    shorts - single letters that may hide inside a short-option cluster
             ("-av" carries "a").
    """
    longs = {f for f in flags if f.startswith("--")}
    shorts = {f[1] for f in flags if f.startswith("-") and not f.startswith("--")}
    return longs, shorts


def flag_present(emerge_args: list[str], flags: tuple[str, ...]) -> bool:
    """True if a flag appears standalone, as a long option, or inside a
    short-option cluster (-av counts as -a)."""
    longs, shorts = _flag_kinds(flags)
    for a in emerge_args:
        if a in longs:
            return True
        if a.startswith("-") and not a.startswith("--") and set(a[1:]) & shorts:
            return True
    return False


def drop_flags(emerge_args: list[str], flags: tuple[str, ...]) -> list[str]:
    """Remove flags everywhere: whole long options, and letters extracted
    from short-option clusters (-av -> -v); a cluster left empty is dropped."""
    longs, shorts = _flag_kinds(flags)
    out: list[str] = []
    for a in emerge_args:
        if a in longs:
            continue
        if a.startswith("-") and not a.startswith("--") and set(a[1:]) & shorts:
            kept = "".join(c for c in a[1:] if c not in shorts)
            if kept:
                out.append("-" + kept)
            continue
        out.append(a)
    return out
