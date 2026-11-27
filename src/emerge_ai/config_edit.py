"""Ladder edits via the apply channel (spec: repair-ladder). Every written line
carries an audit comment; user patches go to /etc/portage/patches/<cat>/<pn>.

A `package.<kind>` channel target may be a directory — the documented Gentoo
layout with one file per category — so the destination is resolved per write
(spec: repair-actions): the line lands in `package.<kind>/<category>`, never in
"a file over a directory", never outside etc_dir. The file name itself is
`channel_file(kind)`, because that is how portage spells it: the license kind
writes `package.license`, not a file named after the kind."""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

from emerge_ai import ui

COMMENT_RE = re.compile(r"^#\s*emerge-ai:")
# a file inside a package.* directory is named after a category: no glob
# characters, no separators — nothing that could escape the directory
_NAME_RE = re.compile(r"[A-Za-z0-9+._-]+")
KINDS = ("use", "accept_keywords", "accept_license", "mask", "unmask", "env")
# where a line without a usable category goes inside a package.* directory
RESERVE_FILE = "emerge-ai"
# kinds whose file is NOT named after the kind, because that is what portage
# spells (spec: repair-actions): LicenseManager reads "package.license" while
# the variable — and our kind — is ACCEPT_LICENSE. package.accept_license is a
# file portage never opens, so writing it would be a silent no-op.
CHANNEL_FILE = {"accept_license": "package.license"}


def channel_file(kind: str) -> str:
    """File name of an edit kind inside etc_dir, spelled the way portage reads
    it. Single source for the write, the undo wording, the walk and the text
    shown at consent, so they cannot name different files."""
    return CHANNEL_FILE.get(kind) or f"package.{kind}"


class ChannelError(RuntimeError):
    """The package-edit channel cannot write its destination (design D4). The
    apply channel turns this into a refusal with a printed reason; it must
    never escape as a traceback from a consented action."""

    def __init__(self, path: str | Path, reason: str):
        super().__init__(f"cannot write {path}: {reason}")
        self.path = str(path)
        self.reason = reason


def audit_comment(journal_id: str, reason: str, now: datetime.date | None = None) -> str:
    d = now or datetime.date.today()
    return f"# emerge-ai: {d.isoformat()} {journal_id or '-'} {reason}"


def category_of(line: str) -> str | None:
    """Category of the atom that opens a package.* line, or None when there is
    nothing to file under (wildcard `*/*`, set atom `@world`, junk): the caller
    falls back to RESERVE_FILE. `tiers.package_of` is reused on purpose — it is
    the project's single atom normalizer (tiers, whitelist @world checks), and
    a second regex here would drift from it on operator prefixes and slots."""
    from emerge_ai.tiers import package_of  # lazy: keeps this module's imports flat

    token = (line or "").split()[:1]
    if not token:
        return None
    cat, sep, _rest = package_of(token[0]).partition("/")
    return cat if sep and _NAME_RE.fullmatch(cat) else None


def resolve_package_target(kind: str, line: str, *,
                           etc_dir: str | Path = "/etc/portage") -> Path:
    """Where this line lands on the host in front of us (design D1): inside the
    directory as `package.<kind>/<category>` when the channel target is a
    directory, the plain channel file otherwise — a host that keeps files keeps
    files, and one that keeps directories is never rewritten. The file name is
    `channel_file(kind)`, so the license kind resolves inside `package.license`.
    """
    target = Path(etc_dir) / channel_file(kind)
    if not target.is_dir():
        return target
    return target / (category_of(line) or RESERVE_FILE)


def destination_label(kind: str, line: str, *, etc_dir: str | Path = "/etc/portage") -> str:
    """The destination the operator is shown, relative to etc_dir, so it reads
    `package.accept_keywords/dev-libs` (spec: shown path = written path)."""
    base = Path(etc_dir) / channel_file(kind)
    target = resolve_package_target(kind, line, etc_dir=etc_dir)
    try:
        return target.relative_to(base.parent).as_posix()
    except ValueError:  # an etc_dir that is not a parent: still the real path
        return str(target)


def apply_package_edit(
    kind: str,
    line: str,
    *,
    reason: str,
    journal_id: str = "",
    etc_dir: str | Path = "/etc/portage",
    now: datetime.date | None = None,
) -> Path:
    """Append `<line> <audit-comment>` to the resolved destination — the channel
    file (`channel_file(kind)`, so `package.license` for the license kind), or
    the category file inside that channel's directory. kind examples: use,
    accept_keywords, accept_license, mask, unmask, env. An unwritable
    destination raises ChannelError (D4)."""
    target = resolve_package_target(kind, line, etc_dir=etc_dir)
    comment = audit_comment(journal_id, reason, now)
    # spec: progress-logging — which file gains which line (stderr only)
    print(ui.activity(f"editing {target}: + {ui.clip(line, 200)}"), file=sys.stderr)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not target.is_file():
            raise ChannelError(target, "the destination exists and is not a regular file")
        with open(target, "a") as fh:
            fh.write(f"{line} {comment}\n")
    except OSError as exc:
        raise ChannelError(target, exc.strerror or str(exc)) from exc
    return target


UNDO_PREFIX = "remove the run's lines (audit marker '# emerge-ai:') from "
UNDO_TABLE = {kind: f"{UNDO_PREFIX}{channel_file(kind)}" for kind in KINDS}


def undo_text(kind: str, *, line: str | None = None,
              etc_dir: str | Path = "/etc/portage") -> str:
    """Mechanically derived cancellation wording per config-edit kind (D3);
    every consent formulation of a package-edit variant shows it. With the
    `line` the wording names the file the line actually goes to (D7); without
    it the wording stays the per-kind one — and both name the file portage
    reads, never the kind name."""
    if line is not None:
        dest = destination_label(kind, line, etc_dir=etc_dir)
        if dest != channel_file(kind):
            return f"{UNDO_PREFIX}{dest}"
    return UNDO_TABLE.get(kind) or (
        f"remove the run's '# emerge-ai:' lines from {channel_file(kind)}")


def _marker_hit(line: str, run_id: str) -> bool:
    return "# emerge-ai:" in line and f" {run_id} " in f" {line} "


def package_files(kind: str | None = None, *,
                  etc_dir: str | Path = "/etc/portage") -> list[Path]:
    """Every file the channel may touch: the channel file of `kind` (all
    `package.*` targets when kind is None) plus, recursively, the files inside
    directory-shaped targets — that is where lines land on a category-layout
    host (design D6). Names come from `channel_file`, so the license kind reads
    `package.license`. Only `package.*` is walked: patches, env, savedconfig
    and repos.conf stay unread and untouched."""
    out: list[Path] = []
    pattern = channel_file(kind) if kind else "package.*"
    for target in sorted(Path(etc_dir).glob(pattern)):
        if target.is_dir():
            out.extend(f for f in sorted(target.rglob("*")) if f.is_file())
        elif target.is_file():
            out.append(target)
    return out


def remove_by_run(run_id: str, *, etc_dir: str | Path = "/etc/portage") -> list[Path]:
    """Undo of config-edit actions (D3): delete lines tagged with this run's
    audit marker across package.* files, category directories included.
    Idempotent — a second call touches nothing; empty files are left empty,
    never removed."""
    touched: list[Path] = []
    if not run_id:
        return touched
    for target in package_files(etc_dir=etc_dir):
        try:
            lines = target.read_text(errors="replace").splitlines()
        except OSError:
            continue
        kept = [ln for ln in lines if not _marker_hit(ln, run_id)]
        if len(kept) != len(lines):
            try:
                target.write_text("\n".join(kept) + ("\n" if kept else ""))
            except OSError:
                continue
            touched.append(target)
    return touched


def get_package_edit_lines(kind: str, *, etc_dir: str | Path = "/etc/portage") -> list[tuple[str, bool]]:
    """(line, is_emerge_ai_audit_comment) for review/GC — every file of the
    kind, a package.<kind> directory included."""
    out = []
    for target in package_files(kind, etc_dir=etc_dir):
        try:
            raw_lines = target.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for raw in raw_lines:
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
    # spec: progress-logging — the patch file written (stderr only)
    print(ui.activity(f"writing patch {path}"), file=sys.stderr)
    path.write_text(f"{header}\n{patch_text}")
    return path
