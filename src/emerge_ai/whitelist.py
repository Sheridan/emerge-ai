"""Whitelisted commands (spec: repair-actions, design D1/D2/D3).

The third action kind of the apply channel next to config-edit and overlay
copies: a CLOSED registry of fixed argv templates. The model may only fill
validated slots; a free argv, path or command is never executed. Commands run
as the real binaries (emaint/emerge) via subprocess — emerge-ai never
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
from dataclasses import dataclass, field
from pathlib import Path

from emerge_ai import gate, portage_compat, ui

WORLD_FILE = "/var/lib/portage/world"

# slot values are single argv elements: no whitespace, no shell metacharacters,
# never a flag (defense in depth on top of shell-less subprocess)
SLOT_VALUE_RE = re.compile(r"^[A-Za-z0-9+/=<>~._:@,-]+$")
ATOM_RE = re.compile(
    r"^(?:[<>=]=?)?[a-z][a-z0-9+_.-]*/[A-Za-z][A-Za-z0-9+_.-]*(?:-\d[\w.]*(?:-r\d+)?)?(?::.+)?$"
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
    ),
}


def _cat_pkg(atom: str) -> str:
    """cat/pkg of an atom via tiers.package_of — world entries and slot atoms
    compare on the same key the tier machinery uses."""
    from emerge_ai.tiers import package_of

    return package_of(atom)


def _validate_atom(value: str, world) -> list[str]:
    if not ATOM_RE.match(value):
        return [f"{value!r} is not a package atom"]
    if world is None:
        return [f"cannot check world membership for {value!r}: world file unreadable"]
    key = _cat_pkg(value)
    for entry in world:
        e = entry.strip()
        if e == value or _cat_pkg(e) == key:
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
        return "not undoable by emerge-ai"
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
    dest = Path(f"{world_file}.emerge-ai.{run_id or 'run'}.bak")
    if not dest.exists():
        shutil.copy2(world_file, dest)
    return str(dest)


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
    audit/backup but are still recorded nowhere — nothing changed."""
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
        proc = runner(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reason": f"{name}: {exc}", "argv": argv}
    out = ui.strip_ansi((proc.stdout or "") + (proc.stderr or ""))
    return {"status": "executed", "returncode": proc.returncode, "output": out,
            "argv": argv, "backup": backup, "undo": undo}
