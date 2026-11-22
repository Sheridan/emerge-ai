"""Recovery points: btrfs snapshot (one per run, tier<=4 trigger) + CONTENTS fallback
archive; guarded rollback channel (spec: system-rollback)."""

from __future__ import annotations

import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from emerge_ai.plan import Plan
from emerge_ai.tiers import snapshot_required

SNAP_BASE = "/.snapshots/emerge-ai"
ARCHIVE_BASE = "/var/lib/emerge-ai/archives"
USER_DATA_PREFIXES = ("/home/", "/root/", "/var/cache/", "/var/tmp/", "/tmp/")


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


def _default_btrfs(args: list[str]) -> str:
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
            return prot
        except Exception as exc:
            prot.notes.append(f"snapshot failed ({exc}); falling back to archive")
    else:
        prot.notes.append(f"fs={fstype}: no snapshot support, using archive")
    if contents_fn is None:
        prot.failed = True
        prot.notes.append("no CONTENTS source: cannot archive")
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
    return prot


def cleanup(prot: Protection, *, btrfs=_default_btrfs) -> list[str]:
    """Drop recovery points after a successful run."""
    done = []
    if prot.snapshot:
        try:
            btrfs(["subvolume", "delete", prot.snapshot])
            done.append(f"deleted snapshot {prot.snapshot}")
        except Exception as exc:
            done.append(f"snapshot delete failed: {exc}")
    if prot.archive_dir:
        import shutil

        shutil.rmtree(prot.archive_dir, ignore_errors=True)
        done.append(f"removed archive {prot.archive_dir}")
    return done


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
