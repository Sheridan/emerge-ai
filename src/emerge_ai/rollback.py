"""Recovery points: btrfs snapshot (one per run, tier<=4 trigger) + CONTENTS fallback
archive; guarded rollback channel (spec: system-rollback)."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from emerge_ai import ui
from emerge_ai.plan import Plan
from emerge_ai.tiers import snapshot_required

SNAP_BASE = "/.snapshots/emerge-ai"
ARCHIVE_BASE = "/var/lib/emerge-ai/archives"
USER_DATA_PREFIXES = ("/home/", "/root/", "/var/cache/", "/var/tmp/", "/tmp/")
REGISTRY_NAME = "manifest.json"  # recovery-point registry inside SNAP_BASE


def detect_root_fs() -> str:
    try:
        proc = subprocess.run(
            ["findmnt", "-T", "/", "-no", "FSTYPE"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


@dataclass
class Protection:
    run_id: str
    snapshot: str | None = None
    archive_dir: str | None = None
    archived_files: int = 0
    archived_configs: int = 0
    skipped_user_data: int = 0
    failed: bool = False
    notes: list[str] = field(default_factory=list)


def _registry_path(snap_base: str) -> Path:
    return Path(snap_base) / REGISTRY_NAME


def _registry_write(snap_base: str, entries: list[dict]) -> None:
    try:
        p = _registry_path(snap_base)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(entries, ensure_ascii=False, indent=1))
    except OSError:
        pass  # the registry must never break protect/cleanup


def _registry_register(snap_base: str, record: dict) -> None:
    """Add/replace the run's registry line (idempotent per run_id)."""
    try:
        entries = json.loads(_registry_path(snap_base).read_text())
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []
    entries = [e for e in entries if e.get("run_id") != record["run_id"]]
    entries.append(record)
    _registry_write(snap_base, entries)


def _registry_unregister(snap_base: str, run_id: str) -> None:
    try:
        entries = json.loads(_registry_path(snap_base).read_text())
    except (OSError, ValueError):
        return
    rest = [e for e in entries if isinstance(e, dict) and e.get("run_id") != run_id]
    if len(rest) != len(entries):
        _registry_write(snap_base, rest)


def _register(prot: Protection, plan: Plan | None, snap_base: str) -> None:
    _registry_register(
        snap_base,
        {
            "run_id": prot.run_id,
            "created": time.time(),
            "kind": "snapshot" if prot.snapshot else "archive",
            "path": prot.snapshot or prot.archive_dir or "",
            "packages": [
                {"cpv": e.cpv, "tier": e.tier} for e in (plan.entries if plan else [])
            ],
            "failed": prot.failed,
            "notes": list(prot.notes),
        },
    )


def _default_btrfs(args: list[str]) -> str:
    # spec: progress-rollback visibility (progress-logging): snapshot/delete is a
    # significant action; the findmnt probe in detect_root_fs stays silent
    print(ui.activity(f"running: btrfs {' '.join(args)}"), file=sys.stderr)
    proc = subprocess.run(["btrfs", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"btrfs {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def protect(
    run_id: str,
    plan: Plan | None,
    *,
    fs: str | None = None,
    snap_base: str = SNAP_BASE,
    archive_base: str = ARCHIVE_BASE,
    btrfs=_default_btrfs,
    contents_fn=None,
) -> Protection:
    """Create the single recovery point for this run (never one per package)."""
    prot = Protection(run_id=run_id)
    if plan is not None and not snapshot_required(plan.entries):
        prot.notes.append("rest-tier only queue: snapshot not required")
        return prot
    if plan is not None:
        prot.notes.append(f"tier<=4 packages present: {[e.cpv for e in plan.entries if e.tier <= 4]}")
    fstype = fs or detect_root_fs()
    if fstype == "btrfs":
        try:
            target = f"{snap_base}/{run_id}"
            Path(snap_base).mkdir(parents=True, exist_ok=True)
            btrfs(["subvolume", "snapshot", "-r", "/", target])
            prot.snapshot = target
            prot.notes.append(f"btrfs snapshot: {target}")
            _register(prot, plan, snap_base)
            return prot
        except Exception as exc:
            prot.notes.append(f"snapshot failed ({exc}); falling back to archive")
    else:
        prot.notes.append(f"fs={fstype}: no snapshot support, using archive")
    if contents_fn is None:
        prot.failed = True
        prot.notes.append("no CONTENTS source: cannot archive")
        _register(prot, plan, snap_base)
        return prot
    try:
        arch_dir = Path(archive_base) / run_id
        arch_dir.mkdir(parents=True, exist_ok=True)
        tar_path = arch_dir / "files.tar"
        with tarfile.open(tar_path, "w") as tar:
            for entry in plan.entries if plan else []:
                for path in contents_fn(entry.cpv):
                    if path.startswith(USER_DATA_PREFIXES):
                        prot.skipped_user_data += 1
                        continue
                    real = Path(path)
                    if not real.exists() or not real.is_file():
                        continue
                    is_config = path.startswith("/etc/")
                    prot.archived_configs += is_config
                    prot.archived_files += not is_config
                    tar.add(path, arcname=f"rootfs/{path.lstrip('/')}", recursive=False)
        prot.archive_dir = str(arch_dir)
        (arch_dir / "manifest.json").write_text(
            f'{{"run_id": "{run_id}", "created": {time.time()}, "files": {prot.archived_files},'
            f' "configs": {prot.archived_configs}, "skipped_user_data": {prot.skipped_user_data}}}'
        )
        prot.notes.append(f"fallback archive: {arch_dir}")
    except Exception as exc:
        prot.failed = True
        prot.notes.append(f"archive failed: {exc}")
    _register(prot, plan, snap_base)
    return prot


def cleanup(prot: Protection, *, btrfs=_default_btrfs, snap_base: str = SNAP_BASE) -> list[str]:
    """Drop recovery points after a successful run (registry entry included)."""
    done = []
    gone = True
    if prot.snapshot:
        try:
            btrfs(["subvolume", "delete", prot.snapshot])
            done.append(f"deleted snapshot {prot.snapshot}")
        except Exception as exc:
            gone = False
            done.append(f"snapshot delete failed: {exc}")
    if prot.archive_dir:
        import shutil

        shutil.rmtree(prot.archive_dir, ignore_errors=True)
        gone = gone and not Path(prot.archive_dir).exists()
        done.append(f"removed archive {prot.archive_dir}")
    if gone:
        _registry_unregister(snap_base, prot.run_id)
    return done


@dataclass
class ProtectionRecord:
    run_id: str
    created: float
    kind: str  # snapshot | archive
    path: str
    packages: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    failed: bool = False
    from_manifest: bool = True  # False -> discovered on disk, registry silent
    missing: bool = False  # registry promised it, disk has nothing


def list_protections(
    *, snap_base: str = SNAP_BASE, archive_base: str = ARCHIVE_BASE
) -> list[ProtectionRecord]:
    """Recovery points known to the registry, unioned with what is on disk
    (desyncs surfaced: from_manifest=False for orphan dirs, missing=True for
    registry lines whose artifact is gone). Newest last."""
    records: dict[str, ProtectionRecord] = {}
    try:
        entries = json.loads(_registry_path(snap_base).read_text())
    except (OSError, ValueError):
        entries = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or not e.get("run_id"):
            continue
        rec = ProtectionRecord(
            run_id=e["run_id"],
            created=e.get("created", 0.0),
            kind=e.get("kind", "archive"),
            path=e.get("path", ""),
            packages=e.get("packages", []),
            notes=e.get("notes", []),
            failed=e.get("failed", False),
        )
        if not rec.failed and (not rec.path or not Path(rec.path).exists()):
            rec.missing = True
        records[rec.run_id] = rec
    for base, kind in ((snap_base, "snapshot"), (archive_base, "archive")):
        try:
            dirs = sorted(Path(base).iterdir())
        except OSError:
            continue
        for d in dirs:
            if not d.is_dir() or d.name in records:
                continue
            records[d.name] = ProtectionRecord(
                run_id=d.name,
                created=d.stat().st_mtime,
                kind=kind,
                path=str(d),
                from_manifest=False,
            )
    return sorted(records.values(), key=lambda r: r.created)


def restore_archive(prot: Protection, target_root: str | str = "/") -> str:
    """Online executor for the fallback archive: unpack rootfs/* members under
    target_root, replacing the files the merge touched."""
    if not prot.archive_dir:
        raise ValueError("no archive to restore")
    print(ui.activity(f"restoring archive {prot.archive_dir} into {target_root}"),
          file=sys.stderr)
    root = Path(target_root)
    count = 0
    with tarfile.open(Path(prot.archive_dir) / "files.tar") as tar:
        for m in tar.getmembers():
            name = m.name
            if not name.startswith("rootfs/"):
                continue
            dest = root / name[len("rootfs/"):]
            if m.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not m.isfile():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src:
                dest.write_bytes(src.read())
            count += 1
    return f"restored {count} file(s) from {prot.archive_dir} into {root}"


@dataclass
class RollbackOutcome:
    kind: str  # refused | instructions | restored
    text: str


def rollback(
    prot: Protection,
    *,
    responsibility: bool,
    confirm_fn,
    executor,
    root_subvolume: bool = False,
) -> RollbackOutcome:
    """Effects -> consent -> online restore, or step-by-step manual instructions
    for the root subvolume (artifacts always kept in that case)."""
    effects = (
        f"rollback run {prot.run_id}: "
        + (f"snapshot {prot.snapshot}; " if prot.snapshot else "")
        + (
            f"archive {prot.archive_dir} ({prot.archived_files} files, "
            f"{prot.archived_configs} configs); "
            if prot.archive_dir
            else ""
        )
        + "installed files of the queue will be replaced by pre-merge state"
    )
    if root_subvolume:
        steps = [
            "1. reboot into a rescue environment (root subvolume cannot be swapped online)",
            f"2. mount the filesystem; btrfs subvolume delete /@ (or rename aside)",
            f"3. btrfs subvolume snapshot {prot.snapshot or prot.archive_dir} /@",
            "4. reboot; artifacts were kept, do not delete before verifying",
        ]
        return RollbackOutcome("instructions", effects + "\n" + "\n".join(steps))
    if not responsibility and not confirm_fn(effects):
        return RollbackOutcome("refused", "rollback cancelled by user")
    executor(prot)
    return RollbackOutcome("restored", effects)
