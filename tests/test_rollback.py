import json
import tarfile

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
