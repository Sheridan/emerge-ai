import io
import stat

import pytest

from aimerge.digest import parse_installed
from aimerge.runner import run_emerge_capturing, with_color_flag


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

    from aimerge import state

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


SPLIT_STUB = """#!/usr/bin/env python3
import sys
sys.stdout.write("\\x1b[32mOUT-ONE\\x1b[0m\\n")
sys.stderr.write("\\x1b[33mERR-ONE\\x1b[0m\\n")
sys.stdout.write("OUT-TWO\\n")
sys.stderr.write("ERR-TWO\\n")
sys.exit(3)
"""


def _split_stub(tmp_path):
    path = tmp_path / "emerge"
    path.write_text(SPLIT_STUB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_streams_routed_to_matching_streams(tmp_path, capfd):
    rc, buf = run_emerge_capturing(["-p", "app-misc/split"], emerge_binary=str(_split_stub(tmp_path)))
    assert rc == 3
    captured = capfd.readouterr()
    # our stdout carries ONLY emerge's stdout, byte-for-byte with ANSI (D: spec)
    assert captured.out == "\x1b[32mOUT-ONE\x1b[0m\nOUT-TWO\n"
    # our stderr is emerge's stderr byte-for-byte, plus aimerge's own
    # progress-logging line for the launch (spec: progress-logging)
    lines = captured.err.splitlines(keepends=True)
    announced = [l for l in lines if l.startswith("aimerge: ")]
    assert announced == [f"aimerge: running: {tmp_path}/emerge -p app-misc/split\n"]
    assert "".join(l for l in lines if not l.startswith("aimerge: ")) == (
        "\x1b[33mERR-ONE\x1b[0m\nERR-TWO\n"
    )
    # merged ANSI-stripped buffer feeds incident/enrich
    assert "OUT-ONE" in buf and "OUT-TWO" in buf and "ERR-ONE" in buf and "ERR-TWO" in buf
    assert "\x1b" not in buf


def test_large_output_both_streams_no_deadlock(tmp_path, capfd):
    stub = tmp_path / "emerge"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "chunk = b'x' * 4096 + b'\\n'\n"
        "for _ in range(200):  # ~800 KB per stream, far above the 64K pipe buffer\n"
        "    sys.stdout.buffer.write(chunk)\n"
        "    sys.stderr.buffer.write(chunk)\n"
        "    sys.stdout.buffer.flush(); sys.stderr.buffer.flush()\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    rc, buf = run_emerge_capturing(["-p", "app-misc/big"], emerge_binary=str(stub))
    assert rc == 0  # reached wait(): no deadlock with both pipes saturated
    captured = capfd.readouterr()
    assert captured.out.count("x" * 4096) == 200
    assert captured.err.count("x" * 4096) == 200
    assert buf.count("x" * 4096) == 400  # nothing dropped from the buffer


def test_reader_thread_error_propagates(tmp_path, capfd, monkeypatch):
    from aimerge import ui as runner_ui

    calls = []
    real = runner_ui.strip_ansi

    def flaky(line):
        calls.append(line)
        if len(calls) == 2:
            raise RuntimeError("reader boom")
        return real(line)

    monkeypatch.setattr(runner_ui, "strip_ansi", flaky)
    with pytest.raises(RuntimeError, match="reader boom"):
        run_emerge_capturing(["-p", "app-misc/split"], emerge_binary=str(_split_stub(tmp_path)))


def test_launch_announced_on_stderr_never_on_stdout(tmp_path, capfd):
    # spec: progress-logging — full argv announced before the launch; emerge's
    # stdout passthrough stays byte-identical
    path = tmp_path / "emerge"
    path.write_text(ANSI_STUB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    rc, _ = run_emerge_capturing(["-av", "app-misc/foo"], emerge_binary=str(path))
    captured = capfd.readouterr()
    assert f"aimerge: running: {path} -av app-misc/foo\n" in captured.err
    assert captured.out == RAW
    assert "aimerge:" not in captured.out
