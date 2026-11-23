"""etc-update via LLM (spec: etc-llm-merge).

12.1: detect config-protect from emerge output and show diffs; with the config
option off this is show-only. 12.2: LLM decides keep-current/take-new/merge
with citations; application goes through the standard copy-over flow, atomic
per package, only after explicit confirmation.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from emerge_ai import injection

CFG_SUFFIX_RE = re.compile(r"/\.?_cfg\d{4}_[^/]+$")
PROTECT_RE = re.compile(r"(?:config protected|etc-update|File protections|\.?_cfg\d{4}_)", re.I)
PROTECT_PATH_RE = re.compile(r"(/[^\s'\"]+\.?_cfg\d{4}_[^\s'\"]*)")


def detect(text: str) -> list[str]:
    """Absolute paths of new ._cfgNNNN_ config files mentioned in emerge output."""
    out = []
    for m in PROTECT_PATH_RE.finditer(text):
        p = m.group(1)
        if p not in out:
            out.append(p)
    return out


def original_of(new_path: str) -> str:
    head, name = os.path.split(new_path.rstrip("/"))
    m = re.match(r"\.?(.*)_cfg\d{4}_(.+)$", name)
    return os.path.join(head, f"{m.group(1)}{m.group(2)}") if m else new_path


def show_diff(new_path: str, current_path: str | None = None, label: str = "") -> str:
    current = current_path or original_of(new_path)
    new_text = Path(new_path).read_text(errors="replace").splitlines()
    cur_text = Path(current).read_text(errors="replace").splitlines() if Path(current).exists() else []
    diff = difflib.unified_diff(cur_text, new_text, fromfile=current, tofile=new_path, lineterm="")
    return "\n".join(diff) or f"(no textual difference: {label or current})"


DECISION_SCHEMA = """Answer with ONE JSON object, no prose:
{"action": "keep-current" | "take-new" | "merge",
 "reason": "one sentence",
 "citations": ["path-or-url: quote fragment"],
 "merged_text": "only when action=merge, the FULL final file text"}"""

ETC_SYSTEM = (
    "You are the config-merge assistant of emerge-ai (Gentoo). A package installed a new "
    "config file that portage protected. Decide: keep-current (user's file wins), "
    "take-new (package default wins), or merge (preserve user customizations AND adopt "
    "necessary new upstream options). Cite the documented options from the provided docs "
    "or web excerpts for every claim. If evidence is insufficient, choose keep-current."
)


def build_merge_prompt(new_text: str, current_text: str, docs: list[tuple[str, str]]) -> list[dict]:
    doc_block = "\n\n".join(
        injection.wrap_untrusted(f"{src}\n{text}", source=f"doc:{src}") for src, text in docs
    )
    user = (
        "CURRENT (user) file:\n"
        + injection.wrap_untrusted(current_text, source="current")
        + "\nNEW (package) file:\n"
        + injection.wrap_untrusted(new_text, source="new")
        + "\n\nDOCUMENTATION:\n"
        + (doc_block or "(none; prefer keep-current)")
        + "\n\n"
        + DECISION_SCHEMA
    )
    return [{"role": "system", "content": ETC_SYSTEM}, {"role": "user", "content": user}]


def parse_decision(reply: str) -> dict:
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON decision in reply: {reply[:200]!r}")
    d = json.loads(reply[start : end + 1])
    if d.get("action") not in ("keep-current", "take-new", "merge"):
        raise ValueError(f"bad action: {d.get('action')!r}")
    if d["action"] == "merge" and "merged_text" not in d:
        raise ValueError("merge without merged_text")
    if not d.get("citations"):
        raise ValueError("decision without citations")
    return d


def llm_decide(client, new_path: str, current_path: str, docs: list[tuple[str, str]]) -> dict:
    new_text = Path(new_path).read_text(errors="replace")
    current_text = Path(current_path).read_text(errors="replace") if Path(current_path).exists() else ""
    reply = client.chat(build_merge_prompt(new_text, current_text, docs))
    reply = getattr(reply, "content", reply) or ""
    return parse_decision(reply)


def apply_decision(
    new_path: str,
    decision: dict,
    *,
    confirm_fn,
    current_path: str | None = None,
    backup_suffix: str = ".pre-emerge-ai",
) -> dict:
    """Only mutation point; atomic replace; user override already baked into
    `decision` by the caller. keep-current leaves everything untouched."""
    current = current_path or original_of(new_path)
    action = decision["action"]
    if action == "keep-current":
        return {"applied": False, "action": action}
    final_text = Path(new_path).read_text(errors="replace") if action == "take-new" else decision["merged_text"]
    prompt = (
        f"etc-update: {action} for {current} "
        f"({decision.get('reason', '')}) — apply? [y/N] "
    )
    if not confirm_fn(prompt):
        return {"applied": False, "action": action, "declined": True}
    if Path(current).exists():
        Path(str(current) + backup_suffix).write_bytes(Path(current).read_bytes())
    tmp = tempfile.NamedTemporaryFile(
        "w", dir=str(Path(current).parent), delete=False, prefix=".emerge-ai-", suffix=".tmp"
    )
    try:
        tmp.write(final_text if final_text.endswith("\n") else final_text + "\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.chmod(tmp.name, Path(new_path).stat().st_mode & 0o777)
    os.replace(tmp.name, current)  # atomic, штатное средство (rename в тот же fs)
    if Path(new_path).exists():
        Path(new_path).unlink()
    return {"applied": True, "action": action, "path": current}


def collect_docs(
    current_path: str,
    web_fetch=None,
    doc_roots: tuple[str, ...] = ("/usr/share/doc", "/usr/share/man"),
) -> list[tuple[str, str]]:
    """Documented docs from readable man/share excerpts; web excerpts only when
    web_fetch is provided (config web_access)."""
    stem = Path(current_path).name.lower().split(".")[0]
    key = stem.split("_")[0]
    docs: list[tuple[str, str]] = []
    for root in doc_roots:
        p = Path(root)
        if not p.is_dir():
            continue
        for f in sorted(p.rglob(f"*{key}*")):
            if f.is_file():
                try:
                    docs.append((str(f), f.read_text(errors="replace")[:4000]))
                except OSError:
                    continue
                if len(docs) >= 4:
                    break
        if len(docs) >= 4:
            break
    if web_fetch is not None:
        docs.extend(web_fetch(current_path))
    return docs[:4]


def parse_override(text: str, decision: dict) -> dict:
    """User replaces the LLM decision (spec 12.2): '', y -> keep LLM decision."""
    text = text.strip()
    if text.lower() in ("", "y", "yes", "n", "no"):
        if text.lower() in ("n", "no"):
            return {"action": "keep-current", "reason": "user declined", "citations": ["user"]}
        return decision
    low = text.lower()
    if low in ("keep-current", "take-new"):
        return {"action": low, "reason": "user override", "citations": ["user"]}
    if low.startswith("merge"):
        parts = text.split(" ", 1)
        if len(parts) != 2:
            raise ValueError("merge needs a file path: merge <path>")
        return {
            "action": "merge",
            "merged_text": Path(parts[1]).read_text(errors="replace"),
            "reason": f"user override merge from {parts[1]}",
            "citations": ["user"],
        }
    raise ValueError(f"unknown override {text!r}")
