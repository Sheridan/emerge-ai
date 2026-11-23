"""Decision journal (spec: decision-journal): JSONL of VERIFIED successes only,
normalized fingerprints, precedent lookup reused by the incident agent."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

JOURNAL_PATH = "/var/log/emerge-ai/journal.jsonl"

NORMALIZERS = [
    (re.compile(r"/var/tmp/portage/[^\s\"']+"), "<path>"),
    (re.compile(r"/(?:[\w+.-]+/)+[\w+.-]*"), "<path>"),
    (re.compile(r"0x[0-9a-f]+"), "<hex>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\b", re.IGNORECASE), "<ts>"),
    (re.compile(r"pid=\d+"), "pid=<n>"),
    (re.compile(r"(?<![\w-])\d+(\.\d+)*"), "<n>"),
]


def normalize_error(text: str) -> str:
    text = text.lower()
    for rx, repl in NORMALIZERS:
        text = rx.sub(repl, text)
    interesting = [
        line.strip()
        for line in text.splitlines()
        if any(k in line for k in ("error", "fail", "denied", "masked", "blocker", "violation"))
    ]
    lines = interesting or [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(dict.fromkeys(lines))  # dedupe, keep order


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_error(text).encode()).hexdigest()[:16]


def record(entry: dict, path: str | Path = JOURNAL_PATH) -> dict:
    entry = {"ts": time.time(), **entry}
    missing = {"fingerprint", "class", "solution", "verified_by", "success", "run_id"} - set(entry)
    if missing:
        raise ValueError(f"journal entry missing fields: {sorted(missing)}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def finalize(
    *,
    run_id: str,
    incident: dict,
    solution: str,
    actions: list[str],
    verified_by: str,
    success: bool,
    overlay_ref: str | None = None,
    path: str | Path = JOURNAL_PATH,
) -> dict | None:
    """Only FINAL, VERIFIED successes enter the journal; failures never do."""
    if not success or not verified_by:
        return None
    return record(
        {
            "fingerprint": fingerprint(incident.get("stderr_tail", "") + incident.get("class", "")),
            "class": incident.get("class", "unknown"),
            "cpv": incident.get("cpv"),
            "context_excerpt": incident.get("stderr_tail", "")[:500],
            "solution": solution,
            "actions": actions,
            "verified_by": verified_by,
            "success": True,
            "run_id": run_id,
            "overlay_ref": overlay_ref,
        },
        path,
    )


def find(
    *,
    fingerprint_value: str | None = None,
    regex: str | None = None,
    path: str | Path = JOURNAL_PATH,
) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rx = re.compile(regex, re.IGNORECASE) if regex else None
    out = []
    for line in p.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if fingerprint_value and entry.get("fingerprint") != fingerprint_value:
            continue
        if rx and not rx.search(json.dumps(entry, ensure_ascii=False)):
            continue
        out.append(entry)
    return out
