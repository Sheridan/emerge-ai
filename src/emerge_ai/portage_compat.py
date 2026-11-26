"""Thin read-only adapter around portage internals.

Single point of contact with portage/`_emerge` internals (design D1/D2): every
read of depgraph, sets, vdb or portageq goes through this module, so a portage
3.0.x minor bump breaks — and gets fixed — in exactly one place.
"""

from __future__ import annotations

import importlib
import subprocess


class PortageUnavailable(RuntimeError):
    pass


def load_portage():
    try:
        return importlib.import_module("portage")
    except ImportError as exc:  # pragma: no cover - depends on host
        raise PortageUnavailable(
            "portage python API is not importable in this interpreter "
            "(emerge-ai must run under the interpreter that owns sys-apps/portage)"
        ) from exc


def portage_version() -> str:
    portage = load_portage()
    version = getattr(portage, "VERSION", None)
    if not version:  # pragma: no cover - defensive
        raise PortageUnavailable("portage module exposes no VERSION")
    return str(version)


def load_emerge_config(action: str, args: list[str], opts: dict):
    """Build emerge_config exactly like emerge's main() does."""
    actions = importlib.import_module("_emerge.actions")
    return actions.load_emerge_config(action=action, args=args, opts=opts)


def resolve(emerge_config, spinner=None):
    """Run the resolver (read-only; pass --pretend/--nodeps via opts as needed).

    Returns (success, depgraph, favorites).
    """
    depgraph_mod = importlib.import_module("_emerge.depgraph")
    params_mod = importlib.import_module("_emerge.create_depgraph_params")
    settings, trees, _mtimedb = emerge_config
    myopts = emerge_config.opts
    myparams = params_mod.create_depgraph_params(myopts, emerge_config.action)
    return depgraph_mod.backtrack_depgraph(
        settings,
        trees,
        myopts,
        myparams,
        emerge_config.action,
        emerge_config.args,
        spinner,
    )


def config_sets(emerge_config) -> list[str]:
    """Names of all configured sets."""
    return sorted(emerge_config.target_config.setconfig.getSets())


def set_atoms(emerge_config, set_name: str) -> list[str]:
    """Resolved atoms of a configured set (e.g. "world", "system")."""
    atoms = emerge_config.target_config.setconfig.getSetAtoms(set_name, set())
    return sorted(str(atom) for atom in atoms)


def world_atoms(world_path: str = "/var/lib/portage/world") -> list[str]:
    """Atoms listed in the world file (read-only; the file portage itself
    writes). Slot validators go through this module, never through ad-hoc
    readers (design D1/D2 of the thin adapter)."""
    try:
        with open(world_path) as fh:
            text = fh.read()
    except OSError as exc:
        raise PortageUnavailable(f"cannot read world file {world_path}: {exc}") from exc
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _vdb_api():
    return load_portage().vartree().dbapi


def vdb_contents(cpv: str) -> list[str]:
    """Installed file list for a cpv from vdb CONTENTS aux field."""
    raw = vdb_aux(cpv, "CONTENTS")
    names = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("obj", "dir", "sym"):
            names.append(parts[1])
    return names


def installed_cpvs(category: str | None = None) -> list[str]:
    """All (or one-category) installed cpv strings."""
    keys = [str(k) for k in _vdb_api().cpv_all()]
    if category:
        keys = [k for k in keys if k.startswith(f"{category}/")]
    return sorted(keys)


def env_value(key: str) -> str:
    """portageq-compatible environment lookup (subprocess to the real portageq)."""
    proc = subprocess.run(
        ["portageq", "envvar", key],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def vdb_aux(cpv: str, field: str) -> str:
    """Arbitrary vdb aux field (USE, SLOT, REPO...); read-only."""
    return str(_vdb_api().aux_get(cpv, [field])[0])


def emerge_info(emerge_binary: str = "emerge") -> str:
    """Output of `emerge --info`; read-only metadata for the system context."""
    import subprocess

    try:
        proc = subprocess.run(
            [emerge_binary, "--info"], capture_output=True, text=True, timeout=180
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PortageUnavailable(f"emerge --info: {exc}") from exc
    return proc.stdout
