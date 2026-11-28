import datetime

from aimerge import config_edit, ladder, overlay
from conftest import fake_ebuild

TODAY = datetime.date(2026, 3, 1)


def test_package_edit_has_audit_comment(tmp_path):
    p = config_edit.apply_package_edit(
        "accept_keywords", "=cat/pkg-1.0 ~amd64",
        reason="unblock after upstream fix", journal_id="j-42",
        etc_dir=tmp_path, now=TODAY,
    )
    text = p.read_text()
    assert "# aimerge: 2026-03-01 j-42 unblock after upstream fix" in text
    lines = config_edit.get_package_edit_lines("accept_keywords", etc_dir=tmp_path)
    assert lines == [("=cat/pkg-1.0 ~amd64 # aimerge: 2026-03-01 j-42 unblock after upstream fix", True)]


def test_user_patch_lands_in_cat_pn_dir(tmp_path):
    path = config_edit.apply_user_patch(
        "app-misc", "foo", "--- a\n+++ b\n", name="10-fix",
        reason="fix -Werror", journal_id="j-7", patches_dir=tmp_path, now=TODAY,
    )
    assert path == tmp_path / "app-misc" / "foo" / "10-fix.diff"
    assert path.read_text().startswith("# aimerge: 2026-03-01 j-7 fix -Werror")


def test_overlay_add_registers_and_wins_priority(tmp_path, fake_ebuild_cmd):
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    conf = tmp_path / "repos.conf"
    overlay.ensure_layout(root, conf, name="aimerge-test", priority=99, masters="gentoo")
    entry = overlay.add_package(
        "cat/pkg-1.0", repo_root=root, source_dir=src,
        reason="missing dep", journal_id="j-1", ebuild_cmd=fake_ebuild_cmd,
    )
    assert (root / "cat" / "pkg" / "pkg-1.0.ebuild").exists()
    assert (root / "cat" / "pkg" / "Manifest").exists()
    assert (root / "cat" / "files" / "1.0" / "x.txt").exists()
    reg = overlay.load_registry(root)
    assert reg["cat/pkg-1.0"]["journal_id"] == "j-1"
    assert reg["cat/pkg-1.0"]["reason"] == "missing dep"
    conf_text = (conf / "aimerge-test.conf").read_text()
    assert "priority = 99" in conf_text and f"location = {root}" in conf_text
    assert overlay.remove_package("cat/pkg-1.0", repo_root=root)
    assert overlay.load_registry(root) == {}


def test_ladder_picks_minimal_sufficient():
    assert ladder.choose_level("keywords") == "package-edit"
    assert ladder.choose_level("license") == "package-edit"
    assert ladder.choose_level("compile") == "user-patch"
    assert ladder.choose_level("mask") == "mask"
    assert ladder.choose_level("compile", needs_source_change=True) == "user-patch"


def test_overlay_only_when_patch_impossible():
    assert ladder.overlay_justified("compile", user_patch_feasible=False)
    assert not ladder.overlay_justified("compile", user_patch_feasible=True)
    assert not ladder.overlay_justified("keywords", user_patch_feasible=False)


def test_gc_suggests_after_tree_fix_no_autoremove():
    reg = {"cat/pkg-1.0": {"cpv": "cat/pkg-1.0", "reason": "x"}, "cat/keep-2": {"cpv": "cat/keep-2"}}
    cands = ladder.gc_candidates(reg, tree_fixed=lambda cpv: cpv == "cat/pkg-1.0")
    assert [c["cpv"] for c in cands] == ["cat/pkg-1.0"]
    assert "cat/keep-2" in reg
