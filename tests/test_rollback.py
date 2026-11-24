import json
import tarfile
from pathlib import Path

import pytest

from emerge_ai.plan import Plan, PlanEntry
from emerge_ai.rollback import Protection, cleanup, detect_root_fs, protect, rollback

T5 = Plan(entries=[PlanEntry("app-editors/vim-9.1", 5, "hint")])
T1 = Plan(entries=[PlanEntry("sys-libs/glibc-2.42", 1, "hint")])


class FakeBtrfs:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("Read-only file system")
        return ""


def test_snapshot_required_only_tier_1_4(tmp_path):
    b = FakeBtrfs()
    prot = protect("r1", T5, fs="btrfs", snap_base=str(tmp_path), btrfs=b)
    assert prot.snapshot is None and not b.calls

    prot = protect("r2", T1, fs="btrfs", snap_base=str(tmp_path), btrfs=b)
    assert prot.snapshot == f"{tmp_path}/r2"
    assert b.calls[0][:3] == ["subvolume", "snapshot", "-r"]


def test_btrfs_failure_falls_back_to_archive(tmp_path):
    contents = {"cat/pkg-1": ["/usr/bin/env", "/etc/hostname", "/home/u/.bashrc", "/gone/file"]}

    prot = protect(
        "r3",
        Plan(entries=[PlanEntry("cat/pkg-1", 1, "test")]),
        fs="btrfs",
        snap_base=str(tmp_path / "snap"),
        btrfs=FakeBtrfs(fail=True),
        archive_base=str(tmp_path / "arch"),
        contents_fn=lambda cpv: contents[cpv],
    )
    assert prot.snapshot is None and not prot.failed
    manifest = json.loads((tmp_path / "arch" / "r3" / "manifest.json").read_text())
    assert manifest["files"] == 1 and manifest["configs"] == 1
    assert manifest["skipped_user_data"] == 1
    names = tarfile.open(tmp_path / "arch" / "r3" / "files.tar").getnames()
    assert any(n.endswith("/usr/bin/env") for n in names)
    assert not any("/home/" in n for n in names)


def test_non_btrfs_no_snapshot_uses_archive(tmp_path):
    prot = protect("r4", T1, fs="ext4", archive_base=str(tmp_path / "a"), contents_fn=None)
    assert prot.failed and prot.snapshot is None


def test_cleanup_removes_both(tmp_path):
    b = FakeBtrfs()
    arch = tmp_path / "a" / "r5"
    arch.mkdir(parents=True)
    prot = Protection(run_id="r5", snapshot="/snap/r5", archive_dir=str(arch))
    lines = cleanup(prot, btrfs=b)
    assert b.calls == [["subvolume", "delete", "/snap/r5"]]
    assert not arch.exists() and len(lines) == 2


def test_detect_root_fs_real_host():
    assert detect_root_fs()  # real findmnt on the test host returns a fstype


def test_rollback_channel_consent():
    prot = Protection(run_id="r6", snapshot="/snap/r6")
    called = []
    out = rollback(prot, responsibility=False, confirm_fn=lambda e: False, executor=called.append)
    assert out.kind == "refused" and not called

    out = rollback(prot, responsibility=False, confirm_fn=lambda e: True, executor=called.append)
    assert out.kind == "restored" and called == [prot]

    called.clear()
    out = rollback(prot, responsibility=True, confirm_fn=lambda e: False, executor=called.append)
    assert out.kind == "restored" and called == [prot]


def test_rollback_root_subvolume_is_manual_and_keeps_artifacts():
    prot = Protection(run_id="r7", snapshot="/snap/r7")
    called = []
    out = rollback(
        prot,
        responsibility=True,
        confirm_fn=lambda e: True,
        executor=called.append,
        root_subvolume=True,
    )
    assert out.kind == "instructions"
    assert "rescue" in out.text and "/snap/r7" in out.text
    assert not called


# --- recovery-point registry (wire-rollback-channel) ---


def _registry(snap_base):
    return json.loads((Path(snap_base) / "manifest.json").read_text())


def test_registry_written_on_snapshot_and_idempotent(tmp_path):
    snap = tmp_path / "snaps"
    prot = protect("reg1", T1, fs="btrfs", snap_base=str(snap), btrfs=FakeBtrfs())
    (snap / "reg1").mkdir()  # FakeBtrfs does not create the subvolume dir
    entries = _registry(str(snap))
    assert len(entries) == 1 and entries[0]["kind"] == "snapshot"
    assert entries[0]["packages"] == [{"cpv": "sys-libs/glibc-2.42", "tier": 1}]
    protect("reg1", T1, fs="btrfs", snap_base=str(snap), btrfs=FakeBtrfs())
    assert len(_registry(str(snap))) == 1  # idempotent per run_id
    assert prot.snapshot == f"{snap}/reg1"


def test_registry_lists_disk_union_and_desync(tmp_path):
    from emerge_ai.rollback import list_protections

    snap, arch = tmp_path / "snaps", tmp_path / "arch"
    contents = {"sys-libs/glibc-2.42": ["/etc/hostname"]}
    (tmp_path / "etc-host").write_text("h")
    prot = protect(
        "reg2", T1, fs="ext4", snap_base=str(snap), archive_base=str(arch),
        contents_fn=lambda cpv: [str(tmp_path / "etc-host")],
    )
    orphan = arch / "orphan-run"
    orphan.mkdir(parents=True)
    recs = list_protections(snap_base=str(snap), archive_base=str(arch))
    by_id = {r.run_id: r for r in recs}
    assert by_id["reg2"].kind == "archive" and by_id["reg2"].from_manifest
    assert by_id["orphan-run"].from_manifest is False  # disk-only record marked
    Path(prot.archive_dir).rename(prot.archive_dir + ".gone")  # artifact lost
    recs = list_protections(snap_base=str(snap), archive_base=str(arch))
    assert next(r for r in recs if r.run_id == "reg2").missing is True


def test_cleanup_drops_registry_entry(tmp_path):
    from emerge_ai.rollback import list_protections

    snap, arch = tmp_path / "snaps", tmp_path / "arch"
    (tmp_path / "f").write_text("x")
    prot = protect(
        "reg3", T1, fs="ext4", snap_base=str(snap), archive_base=str(arch),
        contents_fn=lambda cpv: [str(tmp_path / "f")],
    )
    assert any(r.run_id == "reg3" for r in list_protections(snap_base=str(snap)))
    cleanup(prot, snap_base=str(snap))
    assert not any(r.run_id == "reg3" for r in list_protections(snap_base=str(snap)))


def test_restore_archive_roundtrip(tmp_path):
    from emerge_ai.rollback import restore_archive

    src = tmp_path / "src"
    src.mkdir()
    (src / "hello.txt").write_text("pre-merge")
    arch = tmp_path / "arch" / "r9"
    arch.mkdir(parents=True)
    with tarfile.open(arch / "files.tar", "w") as tar:
        tar.add(src / "hello.txt", arcname="rootfs/usr/share/hello.txt")
    target = tmp_path / "root"
    prot = Protection(run_id="r9", archive_dir=str(arch))
    msg = restore_archive(prot, target_root=str(target))
    assert "1 file" in msg
    assert (target / "usr/share/hello.txt").read_text() == "pre-merge"
