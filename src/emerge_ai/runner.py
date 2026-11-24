"""Subprocess execution of emerge (design D1: emerge itself is never replaced)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from emerge_ai import ui

EMERGE = "emerge"


def with_color_flag(emerge_args: list[str], stream=None) -> list[str]:
    """Emerge runs with captured stdout, so portage's auto-detect never colors;
    request color explicitly when emerge-ai's own stdout takes it
    (spec: console-output). A user-specified --color is passed through untouched."""
    stream = sys.stdout if stream is None else stream
    args = list(emerge_args)
    if any(a == "--color" or a.startswith("--color=") for a in args):
        return args
    if ui.supports_color(stream):
        args.insert(0, "--color=y")
    return args


def run_emerge_capturing(
    emerge_args: list[str], emerge_binary: str = EMERGE, stdout_stream=None
) -> tuple[int, str]:
    """Run emerge (typically --pretend), mirroring output while buffering it
    for incident parsing and enrichment. No TTY is attached. emerge's stdout
    mirrors to our stdout (or `stdout_stream`, used by the mutation-path plan
    phase to keep stdout a pure merge passthrough) and its stderr to our
    stderr, byte-for-byte
    (spec: console-output); the returned buffer holds both sides ANSI-stripped,
    in read order (not cross-stream normalized), because it feeds parsing and
    the LLM (design D5). Undecodable bytes are replaced, never fatal, and the
    text never carries surrogates (spec: console-output, replace-not-crash)."""
    proc = subprocess.Popen(
        [emerge_binary, *with_color_flag(emerge_args)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Decode per line against the console encoding with "replace": one stray
    # byte must not abort the run before proc.wait() and the incident report.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    buffer: list[str] = []
    lock = threading.Lock()
    failures: list[BaseException] = []

    def pump(stream, mirror) -> None:
        try:
            for raw in stream:  # binary mode: bytes lines, we decode explicitly
                line = raw.decode(encoding, errors="replace")
                mirror.write(line)
                mirror.flush()
                with lock:
                    buffer.append(ui.strip_ansi(line))
        except Exception as exc:  # re-raised after wait(); never swallowed
            with lock:
                failures.append(exc)

    readers = [
        threading.Thread(
            target=pump,
            args=(proc.stdout, sys.stdout if stdout_stream is None else stdout_stream),
            daemon=True,
        ),
        threading.Thread(target=pump, args=(proc.stderr, sys.stderr), daemon=True),
    ]
    for t in readers:
        t.start()
    proc.wait()
    for t in readers:
        t.join()
    if failures:
        raise failures[0]
    return proc.returncode, "".join(buffer)


def confirm(prompt: str = "Proceed? [y/N] ") -> bool:
    """Final consent gate owned by emerge-ai; EOF counts as 'no'.

    Reads sys.stdin via input(); the test seam is patching builtins.input.
    """
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
