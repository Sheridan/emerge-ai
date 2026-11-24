"""Unit tests for overlay.py on tmp roots: no root, no live portage, no ebuild.

Expectations follow the CURRENT behaviour of overlay.py; deviations from the
spec-mandated ideal are marked `as-is` and are candidates for their own
change, not silently endorsed.
"""

import hashlib

import pytest

from emerge_ai import overlay

from conftest import fake_ebuild


def test_repos_conf_entry_format():
    entry = overlay.repos_conf_entry(name="myoverlay", location="/srv/ov", priority=42)
    assert entry.startswith("[myoverlay]\n")
    assert "location = /srv/ov\n" in entry
    assert "priority = 42\n" in entry
    assert "auto-sync = false\n" in entry
    # masters is not part of repos_conf_entry — ensure_layout appends it
    assert "masters" not in entry


def test_ensure_layout_creates_files_and_is_idempotent(tmp_path):
    root = tmp_path / "overlay"
    conf = tmp_path / "repos.conf"
    overlay.ensure_layout(root, conf, name="ea-test", priority=99, masters="gentoo")
    assert (root / "profiles" / "repo_name").read_text() == "ea-test\n"
    assert (root / "metadata" / "layout.conf").read_text() == "masters = gentoo\n"
    text = (conf / "ea-test.conf").read_text()
    assert "[ea-test]" in text
    assert f"location = {root}\n" in text
    assert "masters = gentoo\n" in text  # appended here, not by repos_conf_entry
    overlay.ensure_layout(root, conf, name="ea-test", priority=99, masters="gentoo")
    text2 = (conf / "ea-test.conf").read_text()
    assert text2 == text  # existing conf file is never rewritten (no dup entry)


def test_load_registry_missing_returns_empty(tmp_path):
    assert overlay.load_registry(tmp_path) == {}


def test_add_package_success(tmp_path, fake_ebuild_cmd):
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    conf = tmp_path / "repos.conf"
    overlay.ensure_layout(root, conf, name="ea-test", priority=99, masters="gentoo")
    entry = overlay.add_package(
        "cat/pkg-1.0", repo_root=root, source_dir=src,
        reason="missing dep", journal_id="j-1", ebuild_cmd=fake_ebuild_cmd,
    )
    assert (root / "cat" / "pkg" / "pkg-1.0.ebuild").exists()
    assert (root / "cat" / "pkg" / "Manifest").exists()
    assert (root / "cat" / "files" / "1.0" / "x.txt").read_text() == "data"
    assert "masters = gentoo" in (conf / "ea-test.conf").read_text()
    reg = overlay.load_registry(root)
    # as-is: registry is flat cpv -> entry, versions are not aggregated
    assert list(reg) == ["cat/pkg-1.0"]
    assert reg["cat/pkg-1.0"] == entry
    assert entry["cpv"] == "cat/pkg-1.0"
    assert entry["source"] == str(src)
    assert entry["reason"] == "missing dep"
    assert entry["journal_id"] == "j-1"
    assert entry["ts"] > 0


def test_add_package_ebuild_failure_keeps_registry_clean(tmp_path):
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    with pytest.raises(RuntimeError):
        overlay.add_package("cat/pkg-1.0", repo_root=root, source_dir=src,
                            reason="r", ebuild_cmd=["false"])
    assert overlay.load_registry(root) == {}
    # as-is: the copy lands before `ebuild` runs, so the guard protects only
    # the registry — the copied ebuild stays on disk
    assert (root / "cat" / "pkg" / "pkg-1.0.ebuild").exists()


def test_add_package_fallback_writes_manifest_locally(tmp_path):
    # ebuild_cmd=None means NO external command (there is no EMERGE_AI_EBUILD
    # fallback anywhere) — write_manifest runs in-process
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    overlay.add_package("cat/pkg-1.0", repo_root=root, source_dir=src, reason="r")
    manifest = (root / "cat" / "pkg" / "Manifest").read_text()
    assert manifest.startswith("EBUILD pkg-1.0.ebuild MD5 ")
    assert "SHA512" in manifest and "SIZE" in manifest


def test_write_manifest_structure(tmp_path):
    (tmp_path / "pkg-1.0.ebuild").write_text("EAPI=8\n")
    (tmp_path / "files" / "1.0").mkdir(parents=True)
    (tmp_path / "files" / "1.0" / "x.txt").write_text("data")
    manifest = overlay.write_manifest(tmp_path, [
        "pkg-1.0.ebuild", "files/1.0/x.txt", "missing.txt", "Manifest",
    ])
    lines = manifest.read_text().splitlines()
    # missing.txt and Manifest itself are skipped without raising
    assert len(lines) == 2
    ebuild_line = next(line for line in lines if line.startswith("EBUILD "))
    assert ebuild_line.startswith("EBUILD pkg-1.0.ebuild ")
    data = (tmp_path / "pkg-1.0.ebuild").read_bytes()
    for alg in ("md5", "sha1", "sha256", "sha512"):
        assert f"{alg.upper()} {hashlib.new(alg, data).hexdigest()}" in ebuild_line
    assert f"SIZE {len(data)}" in ebuild_line
    aux = next(line for line in lines if line.startswith("AUX "))
    assert aux.startswith("AUX files/1.0/x.txt ")
    assert "SIZE 4" in aux


def test_add_package_files_dir_absent_from_package_manifest(tmp_path):
    # as-is: add_package copies files/<pv> to <root>/<cat>/files/<pv>, outside
    # the package dir, so those files never reach the package-dir Manifest
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    overlay.add_package("cat/pkg-1.0", repo_root=root, source_dir=src, reason="r")
    manifest = (root / "cat" / "pkg" / "Manifest").read_text()
    assert "EBUILD pkg-1.0.ebuild" in manifest
    assert "files/" not in manifest


def test_remove_package(tmp_path, fake_ebuild_cmd):
    src = fake_ebuild(tmp_path)
    root = tmp_path / "overlay"
    overlay.add_package("cat/pkg-1.0", repo_root=root, source_dir=src,
                        reason="r", ebuild_cmd=fake_ebuild_cmd)
    assert overlay.remove_package("cat/pkg-1.0", repo_root=root) is True
    assert not (root / "cat" / "pkg" / "pkg-1.0.ebuild").exists()
    assert overlay.load_registry(root) == {}
    assert overlay.remove_package("cat/pkg-1.0", repo_root=root) is False
