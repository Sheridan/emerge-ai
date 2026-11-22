"""Enrichment hook slot (wired to the LLM client in group 3+, digests in 13)."""

from __future__ import annotations

from typing import Callable

Hook = Callable[[str, object], None]  # (emerge output text, Mode)

_hook: Hook | None = None


def set_hook(hook: Hook | None) -> None:
    global _hook
    _hook = hook


def run_hook(output: str, mode) -> None:
    if _hook is not None:
        _hook(output, mode)
