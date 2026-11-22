"""Prompt assembly: static rules + generated system context (spec: config-prompts)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

GENERATED_DIR = "/var/lib/emerge-ai/prompts"
ENV_RULES_DIR = "EMERGE_AI_PROMPTS_DIR"
FALLBACK_RULES_DIR = "prompts"


def rules_dir() -> Path:
    env = os.environ.get(ENV_RULES_DIR)
    if env:
        return Path(env)
    return Path(FALLBACK_RULES_DIR)


def load_rules(directory: Path | None = None) -> str:
    d = directory or rules_dir()
    parts = []
    for md in sorted(d.rglob("*.md")):
        parts.append(f"## {md.stem}\n{md.read_text().strip()}")
    if not parts:
        raise FileNotFoundError(f"emerge-ai: no prompt rules found in {d}")
    return "\n\n".join(parts)


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect_context(emerge_info: str, language: str) -> dict:
    profile = ""
    m = re.search(r"^Profile:\s*(.+)$", emerge_info, re.MULTILINE)
    if m:
        profile = m.group(1).strip()
    use_match = re.search(r"^USE:\s*(.+)$", emerge_info, re.MULTILINE)
    return {
        "emerge_info": emerge_info,
        "profile": profile,
        "use_flags": use_match.group(1).strip() if use_match else "",
        "root_fs": _run(["findmnt", "-T", "/", "-no", "FSTYPE"]) or "unknown",
        "init": _read("/proc/1/comm") or "unknown",
        "language": language,
    }


def _read(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def assemble_system_prompt(rules: str, context: dict) -> str:
    return (
        "You are emerge-ai, an assistant wrapped around Gentoo's emerge. "
        "Follow these rules strictly.\n\n"
        f"{rules}\n\n"
        "# Machine context\n"
        f"init: {context['init']}\n"
        f"root filesystem: {context['root_fs']}\n"
        f"profile: {context['profile']}\n"
        f"USE: {context['use_flags']}\n"
        f"emerge --info follows:\n{context['emerge_info']}\n\n"
        f"Always respond in {context['language']} unless the user asks otherwise."
    )


def write_generated(prompt: str, directory: str | Path = GENERATED_DIR, name: str = "system.json") -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(json.dumps({"system_prompt": prompt}, ensure_ascii=False, indent=1))
    return path
