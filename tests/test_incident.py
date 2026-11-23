from pathlib import Path

import pytest

from emerge_ai.incident import build_incident, classify, extract_cpv, extract_phase

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("cycle", "cycle"),
        ("sandbox", "sandbox"),
        ("config-protect", "config-protect"),
        ("license", "license"),
        ("keywords", "keywords"),
        ("use", "use"),
        ("mask", "mask"),
        ("blocks", "blocks"),
        ("noebuild", "blocks"),
        ("fetch", "fetch"),
        ("compile", "compile"),
        ("nofixture_unknown", "unknown"),
    ],
)
def test_classify_fixtures(fixture, expected):
    text = (FIXTURES / f"{fixture}.txt").read_text()
    assert classify(text) == expected


def test_extract_cpv_from_build_log_phase():
    text = ">>> Working directory: /var/tmp/portage/app-misc/foo-1.2.3/temp/build.log\n"
    assert extract_cpv(text) == "app-misc/foo-1.2.3"
    assert extract_phase(text, "compile") == "compile"


def test_build_incident_full_context():
    text = (FIXTURES / "compile.txt").read_text()
    inc = build_incident(1, text, ["-a", "app-misc/foo"])
    assert inc["class"] == "compile"
    assert inc["returncode"] == 1
    assert inc["phase"] == "compile"
    assert inc["cpv"] == "app-misc/foo-1.2.3"
    assert inc["build_log"] == "/var/tmp/portage/app-misc/foo-1.2.3/temp/build.log"
    assert "emake failed" in inc["stderr_tail"]
    assert inc["argv"] == ["-a", "app-misc/foo"]


def test_build_incident_strips_ansi_from_tail():
    colored = (
        "\x1b[1;31m * ERROR: app-misc/foo-1.2.3::gentoo failed (compile phase):\x1b[0m\n"
        " * Build failure!\n * emake failed\n"
    )
    inc = build_incident(1, colored, [])
    assert "\x1b" not in inc["stderr_tail"]
    assert inc["class"] == "compile"
    assert "emake failed" in inc["stderr_tail"]


def test_build_incident_truncates_tail():
    inc = build_incident(1, "x" * 100000, [])
    assert len(inc["stderr_tail"]) == 4000
