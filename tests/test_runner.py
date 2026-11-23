import stat

from emerge_ai.digest import parse_installed
from emerge_ai.runner import run_emerge_capturing

ANSI_STUB = """#!/usr/bin/env python3
import sys
sys.stdout.write("\\x1b[32m[ebuild   N    ]\\x1b[0m app-misc/foo-1.2::gentoo\\n")
sys.stdout.write(">>> Emerging (1 of 1) \\x1b[1;33mapp-misc/foo-1.2::gentoo\\x1b[0m\\n")
"""

RAW = (
    "\x1b[32m[ebuild   N    ]\x1b[0m app-misc/foo-1.2::gentoo\n"
    ">>> Emerging (1 of 1) \x1b[1;33mapp-misc/foo-1.2::gentoo\x1b[0m\n"
)


def test_run_emerge_capturing_stdout_verbatim_buffer_stripped(tmp_path, capsys):
    path = tmp_path / "emerge"
    path.write_text(ANSI_STUB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    rc, buf = run_emerge_capturing(["-p", "app-misc/foo"], emerge_binary=str(path))
    assert rc == 0
    assert capsys.readouterr().out == RAW  # passthrough stays byte-identical
    assert "\x1b" not in buf
    assert "[ebuild   N    ] app-misc/foo-1.2::gentoo" in buf
    assert parse_installed(buf) == ["app-misc/foo-1.2::gentoo"]
