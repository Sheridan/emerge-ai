from emerge_ai.flags import Mode, parse_own_flags
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
