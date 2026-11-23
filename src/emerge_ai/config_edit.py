"""Ladder edits via the apply channel (spec: repair-ladder). Every written line
carries an audit comment; user patches go to /etc/portage/patches/<cat>/<pn>."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

COMMENT_RE = re.compile(r"^#\s*emerge-ai:")


def audit_comment(journal_id: str, reason: str, now: datetime.date | None = None) -> str:
    d = now or datetime.date.today()
    return f"# emerge-ai: {d.isoformat()} {journal_id or '-'} {reason}"


def apply_package_edit(
    kind: str,
    line: str,
    *,
    reason: str,
    journal_id: str = "",
    etc_dir: str | Path = "/etc/portage",
    now: datetime.date | None = None,
) -> Path:
    """Append `<line> <audit-comment>` to package.<kind> (file). kind examples:
    use, accept_keywords, accept_license, mask, unmask, env."""
    target = Path(etc_dir) / f"package.{kind}"
    target.parent.mkdir(parents=True, exist_ok=True)
    comment = audit_comment(journal_id, reason, now)
    with open(target, "a") as fh:
        fh.write(f"{line} {comment}\n")
    return target


def get_package_edit_lines(kind: str, *, etc_dir: str | Path = "/etc/portage") -> list[tuple[str, bool]]:
    """(line, is_emerge_ai_audit_comment) for review/GC."""
    target = Path(etc_dir) / f"package.{kind}"
    if not target.exists():
        return []
    out = []
    for raw in target.read_text().splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if COMMENT_RE.match(stripped):
            out.append((stripped, True))
        else:
            out.append((stripped, "# emerge-ai:" in stripped))
    return out


def apply_user_patch(
    cat: str,
    pn: str,
    patch_text: str,
    *,
    name: str = "10-emerge-ai-fix",
    reason: str,
    journal_id: str = "",
    patches_dir: str | Path = "/etc/portage/patches",
    now: datetime.date | None = None,
) -> Path:
    dest = Path(patches_dir) / cat / pn
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}.diff"
    header = audit_comment(journal_id, reason, now)
    path.write_text(f"{header}\n{patch_text}")
    return path
