"""Read-only tests against the live portage on this host (design D13)."""

import pytest

from emerge_ai import portage_compat as pc
from emerge_ai.compat import check_version_compat


@pytest.fixture(scope="module")
def emerge_config():
    return pc.load_emerge_config(action="build", args=[], opts={"--pretend": True})


def test_live_portage_is_compatible():
    result = check_version_compat(pc.portage_version(), "3.0.82")
    assert result.ok, result.message


def test_env_value_matches_portageq_cli():
    assert pc.env_value("ROOT") == "/"


def test_installed_cpvs_and_contents_are_readable():
    cpvs = pc.installed_cpvs()
    assert cpvs
    sample = next(
        (c for c in cpvs if c.startswith(("app-eselect/", "sys-apps/"))),
        cpvs[0],
    )
    contents = pc.vdb_contents(sample)
    assert contents
    assert all(name.startswith("/") for name in contents[:10])


def test_vdb_aux_slot_readable():
    cpv = pc.installed_cpvs("sys-apps")[0]
    slot = pc.vdb_aux(cpv, "SLOT")
    assert slot


def test_world_set_resolves_via_emerge_config(emerge_config):
    assert "world" in pc.config_sets(emerge_config)
    atoms = pc.set_atoms(emerge_config, "world")
    assert atoms and atoms == sorted(atoms)


def test_resolve_pretend_smoke(capsys):
    cfg = pc.load_emerge_config(
        action="build",
        args=["sys-apps/portage"],
        opts={"--pretend": True, "--oneshot": True, "--nodeps": True, "--quiet": True},
    )
    success, graph, _favorites = pc.resolve(cfg)
    assert success
    merged = list(graph.altlist())
    assert merged, "pretend resolver returned empty merge list"
    assert any("sys-apps/portage" in str(entry) for entry in merged)
