"""Live stand check for task 11.2: dummy category resolved through the real
portage stack; the emerge-ai overlay repo wins the base tree by priority."""

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.integration

OVERLAY = "/var/db/repos/emerge-ai-test"
BASE = "/var/db/repos/emerge-ai-test-base"


def test_repos_conf_present():
    for repo in ("emerge-ai-test", "emerge-ai-test-base"):
        conf = f"/etc/portage/repos.conf/{repo}.conf"
        assert os.path.exists(conf), f"stand missing {conf} (see LIVE_CHECKS.md)"
        assert "priority" in open(conf).read()


def test_registry_filled():
    reg = json.loads(open(f"{OVERLAY}/registry.json").read())
    entry = reg["ea-test/foo-1.0"]
    assert entry["journal_id"] == "live-11.2"
    assert entry["source"].startswith(BASE)
    assert entry["reason"]


def test_overlay_ebuild_wins_tree():
    env = dict(os.environ, ACCEPT_KEYWORDS="~amd64")
    proc = subprocess.run(
        ["emerge", "-p", "--verbose", "=ea-test/foo-1.0"],
        capture_output=True, text=True, env=env,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-500:]
    merge_lines = [l for l in out.splitlines() if l.startswith("[ebuild")]
    assert merge_lines, out[-400:]
    assert "::emerge-ai-test" in merge_lines[0]
    assert "emerge-ai-test-base" not in merge_lines[0]
