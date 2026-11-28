"""Init-system detection (spec: cli-compat «Поддержка только systemd»).

The canonical systemd sign is the runtime directory /run/systemd/system; the
fallback is the pid-1 process name. Anything unreadable or unknown counts as
not-systemd (fail-closed): mutations are refused unless systemd is proven."""

from __future__ import annotations

import os
from pathlib import Path

SYSTEMD_MARKER = "/run/systemd/system"


def _proc1_comm() -> str:
    return Path("/proc/1/comm").read_text().strip()


def _probe(path_exists, proc1_comm) -> str:
    try:
        if path_exists(SYSTEMD_MARKER):
            return "systemd"
        return proc1_comm().strip() or "unknown"
    except Exception:
        return "unknown"


def detected_init(*, path_exists=os.path.isdir, proc1_comm=_proc1_comm) -> str:
    """Human-readable init flavor: "systemd", a pid-1 name ("openrc-init"),
    or "unknown" when nothing could be read."""
    return _probe(path_exists, proc1_comm)


def is_systemd(*, path_exists=os.path.isdir, proc1_comm=_proc1_comm) -> bool:
    return _probe(path_exists, proc1_comm) == "systemd"
