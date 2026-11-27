"""Write channel to /etc/portage (spec: repair-ladder) — pinned contract (L3).

Every call below passes an explicit etc_dir/patches_dir into tmp; defaults
point at the real system and must stay untouched by tests."""

import datetime

import pytest

from emerge_ai import config_edit

D = datetime.date(2026, 11, 24)


def test_audit_comment_format():
    assert config_edit.audit_comment("abc123", "unmask for build", D) == (
        "# emerge-ai: 2026-11-24 abc123 unmask for build"
    )
    assert config_edit.audit_comment("", "no journal", D) == (
        "# emerge-ai: 2026-11-24 - no journal"
    )


@pytest.mark.parametrize("kind", ["use", "accept_keywords", "mask"])
def test_apply_package_edit_appends_one_line(tmp_path, kind):
    target = config_edit.apply_package_edit(
        kind, "dev-libs/foo static-libs", reason="needs static", journal_id="j1",
        etc_dir=tmp_path, now=D,
    )
    assert target == tmp_path / f"package.{kind}"
    assert target.read_text() == (
        "dev-libs/foo static-libs # emerge-ai: 2026-11-24 j1 needs static\n"
    )


def test_apply_package_edit_creates_missing_dirs(tmp_path):
    target = config_edit.apply_package_edit(
        "use", "a/b x", reason="r", etc_dir=tmp_path / "portage" / "nested", now=D
    )
    assert target.exists()


def test_apply_package_edit_appends_without_dedup(tmp_path):
    for _ in range(2):
        config_edit.apply_package_edit(
            "use", "a/b x", reason="r", journal_id="j", etc_dir=tmp_path, now=D
        )
    lines = (tmp_path / "package.use").read_text().splitlines()
    # current contract: repeated calls append duplicates, no dedup
    assert len(lines) == 2 and lines[0] == lines[1]


def test_write_stays_inside_etc_dir(tmp_path):
    root = tmp_path / "etc"
    config_edit.apply_package_edit("use", "a/b x", reason="r", etc_dir=root, now=D)
    config_edit.apply_user_patch("cat", "pn", "--- a\n+++ b\n", reason="r",
                                 patches_dir=root / "patches", now=D)
    outside = sorted(p for p in tmp_path.rglob("*") if p.is_file()
                     and root not in p.parents and p != root)
    assert outside == []  # everything landed inside the given root


def test_get_package_edit_lines(tmp_path):
    (tmp_path / "package.use").write_text(
        "\n"
        "dev-libs/old ssl   # user inline note\n"
        "# emerge-ai: 2026-01-01 j0 old audit header\n"
        "dev-libs/new xml # emerge-ai: 2026-01-01 j1 inline audit\n"
        "app-misc/plain flag\n"
    )
    lines = config_edit.get_package_edit_lines("use", etc_dir=tmp_path)
    assert ("dev-libs/old ssl   # user inline note", False) in lines
    assert ("# emerge-ai: 2026-01-01 j0 old audit header", True) in lines
    assert ("dev-libs/new xml # emerge-ai: 2026-01-01 j1 inline audit", True) in lines
    assert ("app-misc/plain flag", False) in lines
    assert len(lines) == 4  # blank line skipped


def test_get_package_edit_lines_missing_file(tmp_path):
    assert config_edit.get_package_edit_lines("use", etc_dir=tmp_path) == []


def test_apply_user_patch_path_and_header(tmp_path):
    path = config_edit.apply_user_patch(
        "app-editors", "vim", "--- a\n+++ b\n@@\n", reason="sandbox fix",
        journal_id="j9", patches_dir=tmp_path / "patches", now=D,
    )
    assert path == tmp_path / "patches" / "app-editors" / "vim" / "10-emerge-ai-fix.diff"
    first, rest = path.read_text().split("\n", 1)
    assert first == "# emerge-ai: 2026-11-24 j9 sandbox fix"
    assert rest == "--- a\n+++ b\n@@\n"


def test_apply_user_patch_same_name_overwrites(tmp_path):
    args = dict(reason="r", patches_dir=tmp_path, now=D)
    config_edit.apply_user_patch("cat", "pn", "old\n", name="50-x", **args)
    config_edit.apply_user_patch("cat", "pn", "new\n", name="50-x", **args)
    assert (tmp_path / "cat" / "pn" / "50-x.diff").read_text() == (
        "# emerge-ai: 2026-11-24 - r\nnew\n"
    )


# --- per-run undo (spec: repair-actions, design D3) ---------------------------

def test_undo_text_exists_for_every_edit_kind():
    for kind in ("use", "accept_keywords", "accept_license", "mask", "unmask", "env"):
        text = config_edit.undo_text(kind)
        assert text.startswith("remove the run's lines") and f"package.{kind}" in text


def test_remove_by_run_deletes_only_that_run(tmp_path):
    config_edit.apply_package_edit("accept_keywords", "=a/b-1 ~amd64", reason="r1",
                                   journal_id="run77", etc_dir=tmp_path, now=D)
    config_edit.apply_package_edit("use", "c/d static", reason="r2",
                                   journal_id="run77", etc_dir=tmp_path, now=D)
    config_edit.apply_package_edit("use", "e/f nls", reason="other",
                                   journal_id="run99", etc_dir=tmp_path, now=D)
    (tmp_path / "package.use").write_text(
        "c/d static # emerge-ai: 2026-11-24 run77 r2\nuser/line keep me\n")

    touched = config_edit.remove_by_run("run77", etc_dir=tmp_path)
    assert {p.name for p in touched} == {"package.accept_keywords", "package.use"}
    assert not (tmp_path / "package.accept_keywords").read_text().strip()
    assert (tmp_path / "package.use").read_text() == "user/line keep me\n"
    assert (tmp_path / "package.accept_keywords").exists()  # emptied, never removed
    # idempotent: nothing more to remove, files untouched
    assert config_edit.remove_by_run("run77", etc_dir=tmp_path) == []
    assert config_edit.remove_by_run("", etc_dir=tmp_path) == []


def test_writes_are_announced(tmp_path, capsys):
    # spec: progress-logging — which file gains which line/patch (stderr only)
    config_edit.apply_package_edit(
        "use", "dev-libs/foo static-libs", reason="needs static", journal_id="j1",
        etc_dir=tmp_path, now=D)
    assert (f"emerge-ai: editing {tmp_path}/package.use: + dev-libs/foo static-libs"
            in capsys.readouterr().err)
    path = config_edit.apply_user_patch("dev-libs", "foo", "--- a\n+++ b\n",
                                        reason="patch", patches_dir=tmp_path, now=D)
    assert f"emerge-ai: writing patch {path}" in capsys.readouterr().err
