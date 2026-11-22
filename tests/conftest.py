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
sys.exit(int(os.environ.get("EMERGE_STUB_RC", "0")))
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
