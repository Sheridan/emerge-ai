from emerge_ai.flags import OWN_FLAGS, OWN_FLAG_HELP, Mode, parse_own_flags
from emerge_ai.runner import drop_flags, flag_present

ASK = ("-a", "--ask")
PRETEND = ("-p", "--pretend")


def test_flag_present_standalone_and_cluster():
    assert flag_present(["-a", "x"], ASK)
    assert flag_present(["--ask"], ASK)
    assert flag_present(["-av"], ASK)
    assert flag_present(["-eavu", "=x-1"], ASK)
    assert not flag_present(["-v", "--verbose"], ASK)
    assert flag_present(["-pv"], PRETEND)
    assert not flag_present(["--usepkg=y"], PRETEND)


def test_drop_flags_cluster_aware():
    assert drop_flags(["-av", "cat/pkg"], ASK) == ["-v", "cat/pkg"]
    assert drop_flags(["-pv", "cat/pkg"], ASK + PRETEND) == ["-v", "cat/pkg"]
    assert drop_flags(["-a"], ASK) == []
    assert drop_flags(["--ask", "-v", "--pretend"], ASK + PRETEND) == ["-v"]
    assert drop_flags(["-eav", "--usepkg=y", "x"], ASK) == ["-ev", "--usepkg=y", "x"]

RESPONSIBILITY = "--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences"


def test_own_flags_stripped_and_modes_set():
    mode, rest = parse_own_flags(
        ["--noninteractive", "-uDN", RESPONSIBILITY, "@world"]
    )
    assert mode == Mode(noninteractive=True, responsibility=True)
    assert rest == ["-uDN", "@world"]


def test_default_mode_is_interactive():
    mode, rest = parse_own_flags(["-p", "sys-apps/portage"])
    assert mode == Mode()
    assert rest == ["-p", "sys-apps/portage"]


def test_own_flag_exact_match_not_prefix():
    mode, rest = parse_own_flags(["--noninteractiveX", RESPONSIBILITY + "X"])
    assert mode == Mode()
    assert rest == ["--noninteractiveX", RESPONSIBILITY + "X"]


def test_own_flags_recognized_at_any_position():
    mode, rest = parse_own_flags(
        ["-uDN", "--changelog", "sys-apps/foo", RESPONSIBILITY, "--keep-going"]
    )
    assert mode == Mode(changelog=True, responsibility=True)
    assert rest == ["-uDN", "sys-apps/foo", "--keep-going"]


def test_repeated_own_flag_is_idempotent():
    mode, rest = parse_own_flags(["--noninteractive", "--noninteractive", "-p", "x"])
    assert mode == Mode(noninteractive=True)
    assert rest == ["-p", "x"]


def test_help_lists_every_own_flag():
    help_lines = {ln.strip().split()[0] for ln in OWN_FLAG_HELP.splitlines() if ln.strip()}
    for flag in OWN_FLAGS:
        assert flag in help_lines, f"{flag} missing from OWN_FLAG_HELP"


def test_own_flags_table_matches_mode_fields():
    import dataclasses

    assert set(OWN_FLAGS.values()) == {f.name for f in dataclasses.fields(Mode)}
