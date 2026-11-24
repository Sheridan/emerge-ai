import os
import stat
import sys

import pytest

from emerge_ai import overlay


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setenv("EMERGE_AI_CONFIG", str(tmp_path / "emerge-ai.json"))


def fake_ebuild(tmp_path, cpv="cat/pkg-1.0", desc="orig"):
    """Source-tree package dir with an ebuild and files/<pv>/ payload."""
    cat, pn, pv = overlay._split_cpv(cpv)
    src = tmp_path / "tree" / cat / pn
    src.mkdir(parents=True)
    ebuild = src / f"{pn}-{pv}.ebuild"
    ebuild.write_text(f'EAPI=8\nDESCRIPTION="{desc}"\nSLOT="0"\nKEYWORDS="~amd64"\nS=${{WORKDIR}}\n')
    (src.parent / "files" / pv).mkdir(parents=True)
    (src.parent / "files" / pv / "x.txt").write_text("data")
    return src


@pytest.fixture
def fake_ebuild_cmd(tmp_path):
    script = tmp_path / "fake-ebuild.sh"
    script.write_text('#!/bin/sh\ntouch "$(dirname "$1")/Manifest"\nexit 0\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return [str(script)]

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
if "--pretend" in sys.argv or "-p" in sys.argv:
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
