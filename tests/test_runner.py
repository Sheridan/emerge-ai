import io
import stat

from emerge_ai.digest import parse_installed
from emerge_ai.runner import run_emerge_capturing, with_color_flag


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_with_color_flag_injects_only_on_colorful_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    assert with_color_flag(["-uDN", "@world"], stream=TTY()) == ["--color=y", "-uDN", "@world"]
    assert with_color_flag(["-uDN", "@world"], stream=io.StringIO()) == ["-uDN", "@world"]
    monkeypatch.setenv("NO_COLOR", "1")
    assert with_color_flag(["-uDN", "@world"], stream=TTY()) == ["-uDN", "@world"]


def test_with_color_flag_respects_user_color():
    for user in (["--color", "n"], ["--color=n"], ["-av", "--color=m"]):
        assert with_color_flag(user, stream=TTY()) == user

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


BYTE_STUB = """#!/usr/bin/env python3
import sys
sys.stdout.buffer.write(b">>> Emerging app-misc/bad\\xff-name-1.0::gentoo\\n")
sys.stdout.buffer.flush()
sys.stderr.buffer.write(b"calc dependencies for bad\\xff-name failed\\n")
sys.stderr.buffer.flush()
sys.exit(1)
"""


def _byte_stub(tmp_path):
    path = tmp_path / "emerge"
    path.write_text(BYTE_STUB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_run_emerge_capturing_replaces_undecodable_bytes(tmp_path, capsys):
    rc, buf = run_emerge_capturing(["-p", "app-misc/bad"], emerge_binary=str(_byte_stub(tmp_path)))
    assert rc == 1  # the run completed: wait() was reached despite bad bytes
    out = capsys.readouterr().out
    assert "\ufffd" in out and "\ufffd" in buf  # replacement, not a crash
    assert ">>> Emerging app-misc/bad" in buf and "-name-1.0::gentoo" in buf
    assert "calc dependencies for bad" in buf  # stderr (merged) survived too
    # invariant: no surrogates in the captured text
    assert not any("\ud800" <= c <= "\udfff" for c in buf)


def test_captured_replacement_survives_run_report(tmp_path, capsys):
    # the captured text must serialize into the run state file (state.save_run,
    # json.dumps with ensure_ascii=False) without an encoding error
    import json

    from emerge_ai import state

    _, buf = run_emerge_capturing(["-p", "app-misc/bad"], emerge_binary=str(_byte_stub(tmp_path)))
    capsys.readouterr()
    run = state.RunState(run_id="report-check", state=state.MERGE)
    run.incident = {"output": buf}
    path = state.save_run(run, tmp_path)
    text = path.read_bytes().decode("utf-8")  # valid UTF-8 end to end
    assert json.loads(text)["incident"]["output"] == buf


def test_run_emerge_capturing_valid_utf8_untouched(tmp_path, capsys):
    stub = tmp_path / "emerge"
    line = "[ebuild   R    ] app-misc/пакет-1.0::gentoo\n"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.buffer.write({line.encode('utf-8')!r})\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    rc, buf = run_emerge_capturing(["-p", "app-misc/pkg"], emerge_binary=str(stub))
    assert rc == 0
    assert capsys.readouterr().out == line  # byte-identical, no replacements
    assert buf == line
    assert "\ufffd" not in buf
