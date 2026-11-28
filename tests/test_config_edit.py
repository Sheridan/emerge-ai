"""Write channel to /etc/portage (spec: repair-ladder) — pinned contract (L3).

Every call below passes an explicit etc_dir/patches_dir into tmp; defaults
point at the real system and must stay untouched by tests."""

import datetime

import pytest

from aimerge import config_edit

D = datetime.date(2026, 11, 24)


def test_audit_comment_format():
    assert config_edit.audit_comment("abc123", "unmask for build", D) == (
        "# aimerge: 2026-11-24 abc123 unmask for build"
    )
    assert config_edit.audit_comment("", "no journal", D) == (
        "# aimerge: 2026-11-24 - no journal"
    )


@pytest.mark.parametrize("kind", ["use", "accept_keywords", "mask"])
def test_apply_package_edit_appends_one_line(tmp_path, kind):
    target = config_edit.apply_package_edit(
        kind, "dev-libs/foo static-libs", reason="needs static", journal_id="j1",
        etc_dir=tmp_path, now=D,
    )
    assert target == tmp_path / f"package.{kind}"
    assert target.read_text() == (
        "dev-libs/foo static-libs # aimerge: 2026-11-24 j1 needs static\n"
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
        "# aimerge: 2026-01-01 j0 old audit header\n"
        "dev-libs/new xml # aimerge: 2026-01-01 j1 inline audit\n"
        "app-misc/plain flag\n"
    )
    lines = config_edit.get_package_edit_lines("use", etc_dir=tmp_path)
    assert ("dev-libs/old ssl   # user inline note", False) in lines
    assert ("# aimerge: 2026-01-01 j0 old audit header", True) in lines
    assert ("dev-libs/new xml # aimerge: 2026-01-01 j1 inline audit", True) in lines
    assert ("app-misc/plain flag", False) in lines
    assert len(lines) == 4  # blank line skipped


def test_get_package_edit_lines_missing_file(tmp_path):
    assert config_edit.get_package_edit_lines("use", etc_dir=tmp_path) == []


def test_apply_user_patch_path_and_header(tmp_path):
    path = config_edit.apply_user_patch(
        "app-editors", "vim", "--- a\n+++ b\n@@\n", reason="sandbox fix",
        journal_id="j9", patches_dir=tmp_path / "patches", now=D,
    )
    assert path == tmp_path / "patches" / "app-editors" / "vim" / "10-aimerge-fix.diff"
    first, rest = path.read_text().split("\n", 1)
    assert first == "# aimerge: 2026-11-24 j9 sandbox fix"
    assert rest == "--- a\n+++ b\n@@\n"


def test_apply_user_patch_same_name_overwrites(tmp_path):
    args = dict(reason="r", patches_dir=tmp_path, now=D)
    config_edit.apply_user_patch("cat", "pn", "old\n", name="50-x", **args)
    config_edit.apply_user_patch("cat", "pn", "new\n", name="50-x", **args)
    assert (tmp_path / "cat" / "pn" / "50-x.diff").read_text() == (
        "# aimerge: 2026-11-24 - r\nnew\n"
    )


# --- per-run undo (spec: repair-actions, design D3) ---------------------------

def test_undo_text_exists_for_every_edit_kind():
    for kind in config_edit.KINDS:
        text = config_edit.undo_text(kind)
        assert text.startswith("remove the run's lines")
        assert config_edit.channel_file(kind) in text  # the file portage reads


def test_remove_by_run_deletes_only_that_run(tmp_path):
    config_edit.apply_package_edit("accept_keywords", "=a/b-1 ~amd64", reason="r1",
                                   journal_id="run77", etc_dir=tmp_path, now=D)
    config_edit.apply_package_edit("use", "c/d static", reason="r2",
                                   journal_id="run77", etc_dir=tmp_path, now=D)
    config_edit.apply_package_edit("use", "e/f nls", reason="other",
                                   journal_id="run99", etc_dir=tmp_path, now=D)
    (tmp_path / "package.use").write_text(
        "c/d static # aimerge: 2026-11-24 run77 r2\nuser/line keep me\n")

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
    assert (f"aimerge: editing {tmp_path}/package.use: + dev-libs/foo static-libs"
            in capsys.readouterr().err)
    path = config_edit.apply_user_patch("dev-libs", "foo", "--- a\n+++ b\n",
                                        reason="patch", patches_dir=tmp_path, now=D)
    assert f"aimerge: writing patch {path}" in capsys.readouterr().err


# --- directory layout (spec: repair-actions, design D1/D3) -------------------

AK = "=dev-libs/jemalloc-5.4.0-r2 ~amd64"


@pytest.mark.parametrize("line,want", [
    (AK, "dev-libs"),
    ("app-misc/foo nls", "app-misc"),
    (">=x11-libs/cairo-1.18[kde] X", "x11-libs"),
])
def test_category_of_reuses_the_atom_normalizer(line, want):
    assert config_edit.category_of(line) == want


@pytest.mark.parametrize("line", ["*/* cuda", "@world", "", "static-libs"])
def test_category_of_nothing_to_file_under(line):
    assert config_edit.category_of(line) is None


def test_resolve_target_follows_the_hosts_layout(tmp_path):
    (tmp_path / "package.accept_keywords").mkdir()  # Gentoo per-category layout
    (tmp_path / "package.use").write_text("a/b x\n")  # a host that keeps files
    assert config_edit.resolve_package_target(
        "accept_keywords", AK, etc_dir=tmp_path) == (
        tmp_path / "package.accept_keywords" / "dev-libs")
    assert config_edit.resolve_package_target("use", "c/d y", etc_dir=tmp_path) == (
        tmp_path / "package.use")
    # a missing target stays a file: the layout is never imposed
    assert config_edit.resolve_package_target("mask", "app-misc/z", etc_dir=tmp_path) == (
        tmp_path / "package.mask")
    assert config_edit.destination_label("accept_keywords", AK, etc_dir=tmp_path) == (
        "package.accept_keywords/dev-libs")


def test_apply_package_edit_into_category_directory(tmp_path):
    ak = tmp_path / "package.accept_keywords"
    ak.mkdir()
    (ak / "app-misc").write_text("app-misc/user ** # theirs\n")
    target = config_edit.apply_package_edit(
        "accept_keywords", AK, reason="masked dep", journal_id="j1", etc_dir=tmp_path, now=D)
    assert target == ak / "dev-libs"
    assert target.read_text() == (
        "=dev-libs/jemalloc-5.4.0-r2 ~amd64 # aimerge: 2026-11-24 j1 masked dep\n")
    assert (ak / "app-misc").read_text() == "app-misc/user ** # theirs\n"  # untouched
    assert ak.is_dir()  # the directory was never replaced by a file


def test_apply_package_edit_reserve_file_without_category(tmp_path):
    (tmp_path / "package.mask").mkdir()
    target = config_edit.apply_package_edit(
        "mask", "*/* cuda", reason="r", journal_id="j", etc_dir=tmp_path, now=D)
    assert target == tmp_path / "package.mask" / config_edit.RESERVE_FILE
    config_edit.apply_package_edit("mask", "@world cuda", reason="r2", journal_id="j",
                                   etc_dir=tmp_path, now=D)
    assert len(target.read_text().splitlines()) == 2  # append, never rewrite


def test_directory_write_is_announced_with_its_path(tmp_path, capsys):
    # spec: repair-actions — the shown path is the written path
    (tmp_path / "package.accept_keywords").mkdir()
    config_edit.apply_package_edit("accept_keywords", AK, reason="masked dep",
                                   journal_id="j1", etc_dir=tmp_path, now=D)
    assert (f"aimerge: editing {tmp_path}/package.accept_keywords/dev-libs: + {AK}"
            in capsys.readouterr().err)


def test_apply_package_edit_refuses_a_non_file_destination(tmp_path):
    (tmp_path / "package.mask" / "dev-libs").mkdir(parents=True)
    (tmp_path / "package.mask" / "user").write_text("app-misc/keep me\n")
    before = sorted(p.name for p in (tmp_path / "package.mask").iterdir())
    with pytest.raises(config_edit.ChannelError) as excinfo:
        config_edit.apply_package_edit("mask", "dev-libs/foo", reason="r",
                                       etc_dir=tmp_path, now=D)
    assert str(tmp_path / "package.mask" / "dev-libs") in str(excinfo.value)
    assert not isinstance(excinfo.value, IsADirectoryError)
    assert sorted(p.name for p in (tmp_path / "package.mask").iterdir()) == before
    assert (tmp_path / "package.mask" / "user").read_text() == "app-misc/keep me\n"


def test_apply_package_edit_unwritable_destination_is_a_channel_error(tmp_path):
    ak = tmp_path / "package.accept_keywords"
    ak.mkdir()
    ak.chmod(0o500)  # read-only directory: append is impossible
    try:
        with pytest.raises(config_edit.ChannelError) as excinfo:
            config_edit.apply_package_edit("accept_keywords", AK, reason="r",
                                           etc_dir=tmp_path, now=D)
        assert "dev-libs" in str(excinfo.value)
    finally:
        ak.chmod(0o700)


# --- undo/overview reach into the directories (spec: repair-actions, D6) -----

def test_remove_by_run_reaches_into_category_directories(tmp_path):
    dev = tmp_path / "package.accept_keywords" / "dev-libs"
    dev.parent.mkdir()
    dev.write_text(
        "dev-libs/user ** keep me\n"
        "=dev-libs/jemalloc-5.4.0-r2 ~amd64 # aimerge: 2026-11-24 run77 masked dep\n")
    assert config_edit.remove_by_run("run99", etc_dir=tmp_path) == []  # another run
    touched = config_edit.remove_by_run("run77", etc_dir=tmp_path)
    assert touched == [dev]
    assert dev.read_text() == "dev-libs/user ** keep me\n"
    assert dev.exists()  # emptied files are never removed
    assert config_edit.remove_by_run("run77", etc_dir=tmp_path) == []  # idempotent


def test_remove_by_run_empties_a_whole_nested_file(tmp_path):
    deep = tmp_path / "package.use" / "dev-libs" / "foo"
    deep.parent.mkdir(parents=True)
    deep.write_text("dev-libs/foo x # aimerge: 2026-11-24 run5 r\n")
    assert config_edit.remove_by_run("run5", etc_dir=tmp_path) == [deep]
    assert deep.exists() and not deep.read_text().strip()


def test_get_package_edit_lines_reads_a_directory_target(tmp_path):
    use = tmp_path / "package.use"
    (use / "dev-libs").mkdir(parents=True)
    (use / "app-misc").write_text("app-misc/a x\n")
    (use / "dev-libs" / "foo").write_text(
        "dev-libs/foo y # aimerge: 2026-11-24 j1 inline\n")
    (use / "notes").write_text("# aimerge: 2026-01-01 j0 header\n")
    lines = config_edit.get_package_edit_lines("use", etc_dir=tmp_path)
    assert ("app-misc/a x", False) in lines
    assert ("dev-libs/foo y # aimerge: 2026-11-24 j1 inline", True) in lines
    assert ("# aimerge: 2026-01-01 j0 header", True) in lines
    assert config_edit.get_package_edit_lines("mask", etc_dir=tmp_path) == []


def test_package_files_stays_inside_the_package_prefix(tmp_path):
    use = tmp_path / "package.use"
    (use / "dev-libs").mkdir(parents=True)
    (use / "dev-libs" / "foo").write_text("dev-libs/foo x\n")
    (use / "app-misc").write_text("app-misc/bar y\n")
    (tmp_path / "package.env").mkdir()
    (tmp_path / "package.env" / "lto").write_text("LD=lld\n")
    (tmp_path / "repos.conf").mkdir()
    (tmp_path / "repos.conf" / "gentoo.conf").write_text("[DEFAULT]\n")
    (tmp_path / "package.license").write_text("*FAcE-RARE\n")
    got = {p.relative_to(tmp_path).as_posix()
           for p in config_edit.package_files(etc_dir=tmp_path)}
    assert got == {"package.env/lto", "package.license", "package.use/app-misc",
                   "package.use/dev-libs/foo"}


# --- wording names the real file (design D7) --------------------------------

def test_undo_text_names_the_category_file(tmp_path):
    (tmp_path / "package.accept_keywords").mkdir()
    assert config_edit.undo_text("accept_keywords", line=AK, etc_dir=tmp_path) == (
        "remove the run's lines (audit marker '# aimerge:') from "
        "package.accept_keywords/dev-libs")
    # a file-layout host (and a call without a line) keeps the per-kind wording
    assert config_edit.undo_text("accept_keywords", line=AK, etc_dir=tmp_path / "empty") == (
        config_edit.undo_text("accept_keywords"))


# --- the channel file is the name portage reads (spec: repair-actions) ------

# Literal, deliberately not derived from the code: `package.accept_license` is a
# file portage never opens (LicenseManager knows only "package.license"), so a
# kind named after the variable is NOT a valid channel file. Editing the table
# without editing this list fails here.
PORTAGE_CHANNEL_FILES = {
    "use": "package.use",
    "accept_keywords": "package.accept_keywords",
    "accept_license": "package.license",
    "mask": "package.mask",
    "unmask": "package.unmask",
    "env": "package.env",
}


def test_every_kind_names_a_file_portage_reads():
    assert {k: config_edit.channel_file(k) for k in config_edit.KINDS} == PORTAGE_CHANNEL_FILES


def test_license_edit_writes_the_readable_file(tmp_path, capsys):
    """The license kind used to write package.accept_license, which no version
    of portage reads: the write looked like a fix and changed nothing."""
    line = "www-servers/nginx *NEEDED-licence"
    got = config_edit.apply_package_edit("accept_license", line, reason="licence",
                                         journal_id="j1", etc_dir=tmp_path, now=D)
    assert got == tmp_path / "package.license"
    assert got.read_text() == f"{line} # aimerge: 2026-11-24 j1 licence\n"
    assert not (tmp_path / "package.accept_license").exists()
    assert (f"aimerge: editing {tmp_path}/package.license: + {line}"
            in capsys.readouterr().err)


def test_license_channel_honours_the_directory_layout(tmp_path):
    lic = tmp_path / "package.license"
    lic.mkdir()
    (lic / "app-misc").write_text("app-misc/user *FOO\n")
    assert config_edit.resolve_package_target("accept_license", "dev-libs/foo *NEEDED",
                                              etc_dir=tmp_path) == lic / "dev-libs"
    assert config_edit.destination_label("accept_license", "app-misc/foo *NEEDED",
                                         etc_dir=tmp_path) == "package.license/app-misc"
    got = config_edit.apply_package_edit("accept_license", "app-misc/foo *NEEDED",
                                         reason="licence", journal_id="j1",
                                         etc_dir=tmp_path, now=D)
    assert got == lic / "app-misc"  # the layout rule applies to this name as well
    assert (lic / "app-misc").read_text() == (
        "app-misc/user *FOO\n"
        "app-misc/foo *NEEDED # aimerge: 2026-11-24 j1 licence\n")
    assert lic.is_dir()  # the directory was never replaced by a file
    assert not (tmp_path / "package.accept_license").exists()


def test_license_lines_are_reviewed_and_undone_under_that_name(tmp_path):
    lic = tmp_path / "package.license"
    (lic / "dev-libs").parent.mkdir(parents=True)
    (lic / "dev-libs").write_text("dev-libs/user *FOO\n")
    config_edit.apply_package_edit("accept_license", "dev-libs/foo *NEEDED",
                                   reason="licence", journal_id="run7", etc_dir=tmp_path, now=D)
    got = config_edit.get_package_edit_lines("accept_license", etc_dir=tmp_path)
    assert ("dev-libs/user *FOO", False) in got
    assert ("dev-libs/foo *NEEDED # aimerge: 2026-11-24 run7 licence", True) in got
    assert config_edit.get_package_edit_lines("use", etc_dir=tmp_path) == []
    touched = config_edit.remove_by_run("run7", etc_dir=tmp_path)
    assert touched == [lic / "dev-libs"]
    assert (lic / "dev-libs").read_text() == "dev-libs/user *FOO\n"
    assert config_edit.remove_by_run("run7", etc_dir=tmp_path) == []  # idempotent


def test_undo_wording_names_the_license_file(tmp_path):
    assert config_edit.undo_text("accept_license").endswith("package.license")
    (tmp_path / "package.license").mkdir()
    assert config_edit.undo_text(
        "accept_license", line="app-misc/foo *NEEDED",
        etc_dir=tmp_path).endswith("package.license/app-misc")


def test_license_lines_without_a_category_use_the_reserve(tmp_path):
    lic = tmp_path / "package.license"
    lic.mkdir()
    got = config_edit.apply_package_edit("accept_license", "*/* *NEEDED-licence",
                                         reason="licence", journal_id="j1",
                                         etc_dir=tmp_path, now=D)
    assert got == lic / config_edit.RESERVE_FILE
    assert not (tmp_path / "package.accept_license").exists()


def test_license_channel_refuses_a_directory_at_the_category_name(tmp_path):
    lic = tmp_path / "package.license"
    (lic / "app-misc").mkdir(parents=True)
    with pytest.raises(config_edit.ChannelError) as exc:
        config_edit.apply_package_edit("accept_license", "app-misc/foo *NEEDED",
                                       reason="licence", journal_id="j1",
                                       etc_dir=tmp_path, now=D)
    assert exc.value.path == str(lic / "app-misc")  # the refusal names that file
    assert not (tmp_path / "package.accept_license").exists()
