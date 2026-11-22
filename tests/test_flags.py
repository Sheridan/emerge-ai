from emerge_ai.flags import Mode, parse_own_flags

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
