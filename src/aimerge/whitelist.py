"""Whitelisted commands (spec: repair-actions, design D1/D2/D3).

The third action kind of the apply channel next to config-edit and overlay
copies: a CLOSED registry of fixed argv templates. The model may only fill
validated slots; a free argv, path or command is never executed. Commands run
as the real binaries (emaint/emerge) via subprocess — aimerge never
re-implements them (D1) — and every execution passes the single mutation
point: decision audit (gate) plus the pre-execution audit line written here
(argv, slots, backup path, undo text).

Slot validators run twice (D2): before a variant is rendered (no stale menu
entry) and again inside execute() (TOCTOU: a parallel run may have removed
the atom) — a failed re-validation rejects the action with a message, never
an exception, and mutates nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aimerge import gate, portage_compat, ui

WORLD_FILE = "/var/lib/portage/world"

# slot values are single argv elements: no whitespace, no shell metacharacters,
# never a flag (defense in depth on top of shell-less subprocess)
SLOT_VALUE_RE = re.compile(r"^[A-Za-z0-9+/=<>~._:@,-]+$")
# portage atom grammar (a cpv is NOT an atom: "cat/pkg-1.2.3" makes emerge print
# "is not a package atom"): operators are < > <= >= = ~ ~> and each one REQUIRES
# a version, while the bare form carries at most a slot (spec: repair-actions,
# the deselect slot is a verbatim world line). _V is portage's own version
# grammar; in the bare form the name must not END in a version segment — that
# is where portage would cut the (illegal) version out — while real names like
# "font-adobe-100dpi" (100dpi is not a version) stay valid atoms.
_V = r"\d+(?:\.\w+)*(?:_(?:alpha|beta|pre|rc|p)\d{1,2})?(?:_p\d+)?(?:-r\d+)?"
_ATOM_CAT = r"[a-z][a-z0-9+_.-]*"
_ATOM_CPV = _ATOM_CAT + r"/[A-Za-z][A-Za-z0-9+_.-]*"
_ATOM_NAME = r"(?!.*-" + _V + r"(?::.+)?$)[A-Za-z][A-Za-z0-9+_.-]*"
ATOM_RE = re.compile(
    r"^(?:(?:[<>]=?|=|~>?)" + _ATOM_CPV + "-" + _V
    + r"|" + _ATOM_CAT + "/" + _ATOM_NAME + r")(?::.+)?$"
)
PLACEHOLDER_RE = re.compile(r"^\{(\w+)}$")


@dataclass
class CommandSpec:
    """One entry of the closed whitelist. `validators` maps a slot to
    validator names; `backup` names a backup strategy (None -> the command is
    idempotent or read-only); `undo` is mechanically derived wording that the
    consent formulation MUST show (D3)."""

    name: str
    argv_template: tuple[str, ...]
    slots: tuple[str, ...] = ()
    validators: dict[str, tuple[str, ...]] = field(default_factory=dict)
    read_only: bool = False
    backup: str | None = None
    undo: str = ""
    verify: str | None = None  # post-execution effect check (see execute)


COMMANDS: dict[str, CommandSpec] = {
    "emaint-check-world": CommandSpec(
        name="emaint-check-world",
        argv_template=("emaint", "--check", "world"),
        read_only=True,
        undo="nothing to undo: read-only check",
    ),
    "emaint-fix-world": CommandSpec(
        name="emaint-fix-world",
        argv_template=("emaint", "--fix", "world"),
        backup="world",
        undo="restore the world copy {backup} over {world_file}",
    ),
    "emerge-deselect": CommandSpec(
        name="emerge-deselect",
        argv_template=("emerge", "--deselect", "{atom}"),
        slots=("atom",),
        validators={"atom": ("atom",)},
        undo="emerge --noreplace {atom}",
        # emerge exits 0 on 'No matching atoms found in "world"': the effect is
        # only true when the file line is actually gone (spec: repair-actions)
        verify="world-entry-removed",
    ),
}


def _validate_atom(value: str, world) -> list[str]:
    if not ATOM_RE.match(value):
        return [f"{value!r} is not a package atom"]
    if world is None:
        return [f"cannot check world membership for {value!r}: world file unreadable"]
    # Membership is the world line VERBATIM, not a cat/pkg match: portage's
    # action_deselect compares atoms with Atom.intersects(), so a "nearly
    # right" atom (=cat/pkg-1.2.3, another slot) matches nothing while the
    # command still exits 0 — a silent no-op recorded as a fix. Exact match
    # also makes the TOCTOU re-check catch a rewritten line (slot added by a
    # parallel run), not only a removed one.
    if any(e.strip() == value for e in world):
        return []
    return [f"{value!r} is not a member of @world"]


_SLOT_VALIDATORS = {
    "atom": _validate_atom,
}


def validate(name: str, slots: dict, *, world: list[str] | None | bool = True) -> list[str]:
    """Slot validation for rendering (world=True reads the file) and for
    apply-time re-validation (the caller may pass a fresh list). Unknown
    commands/slots fail closed. `world=False` skips membership (format
    checks only)."""
    spec = COMMANDS.get(name)
    if spec is None:
        return [f"unknown whitelisted command {name!r}"]
    errors: list[str] = []
    world_list: list[str] | None | bool = world
    if world is True:
        try:
            world_list = portage_compat.world_atoms()
        except portage_compat.PortageUnavailable as exc:
            world_list = None
            errors.append(str(exc))
    for slot in spec.slots:
        if slot not in slots:
            errors.append(f"missing slot {slot!r}")
    for slot, value in slots.items():
        if slot not in spec.slots:
            errors.append(f"slot {slot!r} is not part of {name!r}")
            continue
        v = str(value)
        if not SLOT_VALUE_RE.match(v) or v.startswith("-"):
            errors.append(f"slot {slot!r}: {v!r} is not a safe single argv value")
            continue
        for kind in spec.validators.get(slot, ()):
            check = _SLOT_VALIDATORS.get(kind)
            if check is None:
                errors.append(f"no validator {kind!r} for slot {slot!r}")
            else:
                errors += check(v, None if world_list is False else world_list)
    return errors


def render_argv(name: str, slots: dict, *, binaries: dict[str, str] | None = None) -> list[str]:
    """Instantiate the fixed template; placeholders fill whole argv elements.
    `binaries` maps template binary -> configured binary (emerge_binary seam)."""
    spec = COMMANDS[name]  # callers validate the name first; unknown -> KeyError
    argv = []
    for part in spec.argv_template:
        m = PLACEHOLDER_RE.match(part)
        if m:
            argv.append(str(slots[m.group(1)]))
        else:
            argv.append(part)
    if binaries and argv[0] in binaries:
        argv[0] = binaries[argv[0]]
    return argv


def undo_text(name: str, slots: dict, *, backup: str = "") -> str:
    """The mechanically derived cancellation wording (D3) shown in the
    consent formulation and recorded in the audit."""
    spec = COMMANDS.get(name)
    if spec is None:
        return "not undoable by aimerge"
    ctx = dict(slots)
    ctx.setdefault("backup", backup or "<run backup>")
    ctx.setdefault("world_file", WORLD_FILE)
    try:
        return spec.undo.format(**ctx)
    except (KeyError, IndexError):
        return spec.undo


def backup_world(run_id: str, *, world_file: str | None = None) -> str:
    """The per-run world copy (idempotent: an existing copy for this run is
    reused, never overwritten); returns the copy path."""
    world_file = world_file or WORLD_FILE
    dest = Path(f"{world_file}.aimerge.{run_id or 'run'}.bak")
    if not dest.exists():
        shutil.copy2(world_file, dest)
    return str(dest)


def _effect_world_entry_removed(atom: str, world_file: str, returncode: int):
    """Effect of `emerge --deselect <atom>` measured against the world file:
    True when the line is gone, False when it is still listed or the command
    failed (portage exits 0 on 'No matching atoms found in \"world\"' — an rc
    is not an effect), None when the file cannot be re-read — unknown, never
    assumed (spec: repair-actions)."""
    if returncode != 0:
        return False
    try:
        entries = portage_compat.world_atoms(world_file)
    except portage_compat.PortageUnavailable:
        return None
    return not any(e.strip() == atom for e in entries)


def execute(name: str, slots: dict, *, run_id: str = "",
            audit_path: str | Path | None = None,
            world: list[str] | None | bool = True,
            binaries: dict[str, str] | None = None,
            world_file: str | None = None,
            runner=subprocess.run, timeout: float = 600.0,
            echo=print) -> dict:
    """The whitelisted-command executor: re-validate (TOCTOU, D2) -> backup ->
    pre-execution audit -> fixed argv. Rejects never mutate and never raise:
    the caller shows `reason` and the menu rebuilds. Read-only commands skip
    audit/backup but are still recorded nowhere — nothing changed. A spec with
    `verify` additionally re-checks the effect after the run: the result then
    carries `changed` and status `no-effect` when the file says nothing
    happened, whatever the exit code said."""
    spec = COMMANDS.get(name)
    if spec is None:
        return {"status": "rejected", "reason": f"unknown whitelisted command {name!r}"}
    if audit_path is None:  # resolved at call time (test isolation, config)
        audit_path = gate.AUDIT_PATH
    world_file = world_file or WORLD_FILE
    if isinstance(world, bool) and world:
        try:
            world = portage_compat.world_atoms(world_file)
        except portage_compat.PortageUnavailable:
            world = None
    errors = validate(name, slots, world=world)
    if errors:
        reason = "; ".join(errors)
        echo(ui.warn(f"whitelist {name}: variant is stale — {reason}; nothing executed"))
        gate.audit({"command": name, "slots": dict(slots), "decision": "rejected-stale",
                    "reason": reason}, audit_path)
        return {"status": "rejected", "reason": reason}
    backup = ""
    if spec.backup == "world":
        try:
            backup = backup_world(run_id, world_file=world_file)
        except OSError as exc:
            reason = f"cannot back up the world file: {exc}"
            echo(ui.err(f"whitelist {name}: {reason}; nothing executed"))
            return {"status": "rejected", "reason": reason}
    argv = render_argv(name, slots, binaries=binaries)
    undo = undo_text(name, slots, backup=backup)
    if not spec.read_only:
        if not gate.audit({"command": name, "argv": argv, "slots": dict(slots),
                           "backup": backup, "undo": undo, "decision": "command-execute"},
                          audit_path):
            echo(ui.err("whitelist: decision audit unwritable — fail-closed, nothing executed"))
            return {"status": "rejected", "reason": "audit unwritable"}
    try:
        # spec: progress-logging — the full whitelisted argv, announced before it runs
        print(ui.activity(f"running: {' '.join(argv)}"), file=sys.stderr)
        proc = runner(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reason": f"{name}: {exc}", "argv": argv}
    out = ui.strip_ansi((proc.stdout or "") + (proc.stderr or ""))
    res = {"status": "executed", "returncode": proc.returncode, "output": out,
           "argv": argv, "backup": backup, "undo": undo}
    if spec.verify == "world-entry-removed":
        # the honest effect (design D3): rc 0 with the line still in the file
        # is a no-op, not a fix — the caller must not count it or re-offer it
        atom = str(slots.get("atom", ""))
        res["changed"] = _effect_world_entry_removed(atom, world_file, proc.returncode)
        if not gate.audit({"command": name, "argv": argv, "slots": dict(slots),
                           "decision": "command-effect", "changed": res["changed"],
                           "returncode": proc.returncode}, audit_path):
            echo(ui.err(f"whitelist {name}: effect audit unwritable — the command "
                        "already ran, check the world file by hand"))
        if res["changed"] is not True:
            echo(ui.err(f"whitelist {name}: no effect — {atom!r} is still listed "
                        "in the world file (or it could not be re-read); not "
                        f"counted as a fix — if intended, run it by hand: "
                        f"emerge --deselect {atom}"))
            res["status"] = "no-effect"
    return res
