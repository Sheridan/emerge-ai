"""Tool sandbox: jailed file access, read-only binary allowlist, web fetch,
pretend_emerge hypothesis checks. Nothing here may mutate the system."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

from emerge_ai import ui

DEFAULT_JAIL_ROOTS = ("/var/tmp/portage", "/var/log/portage", "/var/lib/portage")
MAX_BYTES = 128_000

READONLY_BINARIES = frozenset(
    {
        "cat", "comm", "cmp", "cut", "df", "dirname", "du", "file", "findmnt",
        "grep", "egrep", "fgrep", "rg", "head", "id", "journalctl", "ls",
        "lsblk", "md5sum", "sha256sum", "basename", "portageq", "genlop",
        "readelf", "sort", "stat", "strings", "tail", "tr", "uniq", "uname",
        "wc", "zcat", "bzcat", "xzcat",
    }
)

ENV_OVERRIDE_ALLOWLIST = frozenset(
    {"ACCEPT_KEYWORDS", "ACCEPT_LICENSE", "USE", "PYTHON_TARGETS", "PYTHON_SINGLE_TARGET", "CPU_FLAGS_X86"}
)
PRETEND_FLAGS_ALLOWLIST = frozenset(
    {"--nodeps", "--tree", "--quiet", "--verbose", "--backtrack=30", "--complete-graph", "--with-bdeps=y"}
)


class JailEscape(PermissionError):
    pass


class BinaryNotAllowed(PermissionError):
    pass


class Sandbox:
    def __init__(
        self,
        roots: tuple[str, ...] = DEFAULT_JAIL_ROOTS,
        allowlist: frozenset[str] = READONLY_BINARIES,
        max_bytes: int = MAX_BYTES,
        emerge_binary: str = "emerge",
    ):
        self.roots = [os.path.realpath(r) for r in roots if os.path.exists(r)] or ["/nonexistent"]
        self.allowlist = allowlist
        self.max_bytes = max_bytes
        self.emerge_binary = emerge_binary

    # ------------------------------------------------------------------ files
    def _check(self, path: str) -> str:
        resolved = os.path.realpath(path)
        for root in self.roots:
            if resolved == root or resolved.startswith(root + os.sep):
                return resolved
        raise JailEscape(f"path {path!r} is outside the jail roots {self.roots}")

    def read_file_window(self, path: str, offset: int = 0, limit: int = 200) -> dict:
        real = self._check(path)
        try:
            with open(real, "r", errors="replace") as fh:
                lines = []
                for i, line in enumerate(fh):
                    if i < offset:
                        continue
                    if len(lines) >= limit:
                        break
                    lines.append(line.rstrip("\n"))
        except OSError as exc:
            return {"error": str(exc)}
        return {"path": real, "offset": offset, "lines": lines}

    def grep_log(self, path: str, pattern: str, max_matches: int = 60) -> dict:
        import re as _re

        real = self._check(path)
        try:
            rx = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as exc:
            return {"error": f"bad pattern: {exc}"}
        matches = []
        try:
            with open(real, "r", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if rx.search(line):
                        matches.append({"line": i, "text": line.rstrip("\n")[:400]})
                        if len(matches) >= max_matches:
                            matches.append({"truncated": True})
                            break
        except OSError as exc:
            return {"error": str(exc)}
        return {"path": real, "matches": matches}

    # ------------------------------------------------------------- processes
    def run_readonly(self, argv: list[str], timeout: float = 60.0) -> dict:
        if not argv:
            return {"error": "empty command"}
        binary = os.path.basename(argv[0])
        if binary not in self.allowlist:
            raise BinaryNotAllowed(
                f"{binary!r} is not on the read-only allowlist ({len(self.allowlist)} binaries)"
            )
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": str(exc)}
        out = (proc.stdout or "") + (proc.stderr or "")
        return {"returncode": proc.returncode, "output": out[: self.max_bytes]}

    def journal_search(self, *args: str, max_lines: int = 200) -> dict:
        argv = ["journalctl", "--no-pager", "-o", "short-iso", *args]
        result = self.run_readonly(argv)
        if "output" in result:
            out = ui.strip_ansi(result["output"])
            result["output"] = "\n".join(out.splitlines()[-max_lines:])
        return result

    # -------------------------------------------------------------------- web
    def web_fetch(self, url: str) -> dict:
        import urllib.request

        if not url.startswith("https://"):
            return {"error": "only https:// is allowed"}
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read(self.max_bytes + 1)
        except Exception as exc:
            return {"error": str(exc)}
        text = data[: self.max_bytes].decode("utf-8", errors="replace")
        return {"url": url, "content": text, "truncated": len(data) > self.max_bytes}

    # ------------------------------------------------------------ hypotheses
    def pretend_emerge(
        self,
        atoms: list[str],
        extra_flags: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict:
        """Merge-list dry run with temporary env overrides; nothing is written."""
        for flag in extra_flags or []:
            if flag not in PRETEND_FLAGS_ALLOWLIST:
                return {"error": f"flag {flag!r} not allowed for hypothesis checks"}
        for key in env_overrides or {}:
            if key not in ENV_OVERRIDE_ALLOWLIST:
                return {"error": f"env override {key!r} not allowed"}
        argv = [self.emerge_binary, "--pretend", "--quiet", *(extra_flags or []), *atoms]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ, **(env_overrides or {})},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": str(exc)}
        out = ui.strip_ansi((proc.stdout or "") + (proc.stderr or ""))
        return {
            "returncode": proc.returncode,
            "argv": argv,
            "env_overrides": dict(env_overrides or {}),
            "output": out[: self.max_bytes],
        }
