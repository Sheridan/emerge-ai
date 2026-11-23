import os
import stat
import sys

import pytest

STUB = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("EMERGE_STUB_LOG")
if log:
    with open(log, "a") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
print("STUB-OUT line1")
print("STUB-ERR line1", file=sys.stderr)
err = os.environ.get("EMERGE_STUB_ERR")
if err:
    print(err, file=sys.stderr)
rc = os.environ.get("EMERGE_STUB_RC", "0")
if "--pretend" in sys.argv:
    rc = os.environ.get("EMERGE_STUB_PRETEND_RC", rc)
sys.exit(int(rc))
"""


@pytest.fixture
def emerge_stub(tmp_path, monkeypatch):
    path = tmp_path / "emerge"
    path.write_text(STUB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("EMERGE_STUB_LOG", str(log))

    def calls() -> list[list[str]]:
        if not log.exists():
            return []
        return [line.split() for line in log.read_text().splitlines()]

    return str(path), calls


@pytest.fixture
def jail_log(tmp_path):
    root = tmp_path / "jail"
    root.mkdir()
    log = root / "build.log"
    log.write_text("noise\nerror: something\n")
    return str(log)
