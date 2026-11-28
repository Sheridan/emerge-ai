import pytest

from aimerge.compat import check_version_compat


@pytest.mark.parametrize(
    ("portage_version", "app_version", "ok"),
    [
        ("3.0.82.2", "3.0.82", True),
        ("3.0.82.2", "3.0.82.2", True),
        ("3.0.83", "3.0.82", True),
        ("3.0.80-r1", "3.0.82", True),
        ("3.1.0", "3.0.82", False),
        ("2.3.99", "3.0.82", False),
        ("3.0", "3.1", False),
    ],
)
def test_compat_matrix(portage_version, app_version, ok):
    result = check_version_compat(portage_version, app_version)
    assert result.ok is ok


def test_mismatch_message_names_both_versions():
    result = check_version_compat("3.1.0", "3.0.82")
    assert not result.ok
    assert "3.1.0" in result.message and "3.0.82" in result.message
    assert "major.minor" in result.message
