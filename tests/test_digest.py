import json

from emerge_ai import state
from emerge_ai.digest import parse_installed, post_run_digest

MERGE_OUT = """Calculating dependencies... done!
[ebuild  N     ] app-misc/foo-1.2::gentoo  USE="x"
[ebuild   U    ] dev-libs/bar-2.0::gentoo
>>> Emerging (1 of 2) app-misc/foo-1.2::gentoo
>>> Installing (1 of 2) app-misc/foo-1.2::gentoo
>>> Emerging (2 of 2) dev-libs/bar-2.0::gentoo
>>> Completed (2 of 2) dev-libs/bar-2.0::gentoo
"""


def test_parse_installed():
    assert parse_installed(MERGE_OUT) == ["app-misc/foo-1.2::gentoo", "dev-libs/bar-2.0::gentoo"]


COLORED_MERGE = (
    "\x1b[1;32m[ebuild   N    ]\x1b[0m app-misc/foo-1.2::gentoo  USE=\"x\"\n"
    ">>> Emerging (1 of 1) \x1b[33mapp-misc/foo-1.2::gentoo\x1b[0m\n"
)


def test_parse_installed_survives_ansi():
    assert parse_installed(COLORED_MERGE) == ["app-misc/foo-1.2::gentoo"]


def test_post_run_digest_on_colored_output_lists_packages():
    from emerge_ai.flags import Mode
    run = state.new_run(["world"], Mode())
    text = post_run_digest(run, COLORED_MERGE)
    assert "app-misc/foo-1.2" in text and "nothing" not in text


def test_post_run_digest_content():
    from emerge_ai.flags import Mode
    run = state.new_run(["world"], Mode())
    run.incident = {"class": "compile"}
    run.agent_proposal = "add =dev-libs/bar-2.0 to keywords\nmore text"
    run.protection = {"snapshot": "snap", "archive": None, "failed": False}
    text = post_run_digest(run, MERGE_OUT)
    assert "app-misc/foo-1.2" in text and "dev-libs/bar-2.0" in text
    assert "agent proposed: add =dev-libs/bar-2.0" in text
    assert "recovery point created" in text
    assert "incident compile" in text
