"""Whitelisted commands (spec: repair-actions) — closed registry, slot
validation, TOCTOU re-check, backup, pre-execution audit ordering."""

import json

import pytest

from emerge_ai import whitelist


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def make_runner(calls, rc=0, stdout="ok\n", before=None):
    def runner(argv, **kwargs):
        if before:
            before(list(argv))
        calls.append((list(argv), kwargs))
        return Proc(rc, stdout)
    return runner


def world_file(tmp_path, atoms):
    p = tmp_path / "world"
    p.write_text("\n".join(atoms) + "\n")
    return str(p)


def audit_lines(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# --- D1: closed registry ----------------------------------------------------

def test_registry_is_closed_and_templates_are_fixed():
    assert set(whitelist.COMMANDS) == {"emaint-check-world", "emaint-fix-world",
                                       "emerge-deselect"}
    assert whitelist.render_argv("emaint-fix-world", {}) == ["emaint", "--fix", "world"]
    assert whitelist.render_argv("emaint-check-world", {}) == ["emaint", "--check", "world"]
    assert whitelist.render_argv("emerge-deselect", {"atom": "dev-x/y-1.0"},
                                 binaries={"emerge": "/usr/local/bin/emerge"}) == \
        ["/usr/local/bin/emerge", "--deselect", "dev-x/y-1.0"]


def test_unknown_command_never_executes(tmp_path):
    calls = []
    res = whitelist.execute("curl-pipe-bash", {}, runner=make_runner(calls),
                            audit_path=tmp_path / "audit.jsonl")
    assert res["status"] == "rejected" and calls == []
    res = whitelist.execute("emerge", {"atom": "sys-kernel/gentoo-sources"},
                            runner=make_runner(calls),
                            audit_path=tmp_path / "audit.jsonl")
    assert res["status"] == "rejected" and calls == []


# --- D2: slot validation ------------------------------------------------------

def test_slot_values_are_single_safe_argv_elements():
    bad = ["--help", "dev-x/y ; rm", "dev-x/y\nnext", "$(id)", "", "a/b|c"]
    for value in bad:
        errors = whitelist.validate("emerge-deselect", {"atom": value}, world=[])
        assert errors, f"{value!r} must be rejected"
    assert whitelist.validate("emerge-deselect", {"atom": "dev-x/y-1.0:0::repo"},
                              world=["dev-x/y-1.0"]) == []


def test_slots_shape_is_enforced():
    assert any("missing slot" in e
               for e in whitelist.validate("emerge-deselect", {}, world=[]))
    assert any("not part of" in e
               for e in whitelist.validate("emerge-deselect",
                                           {"atom": "dev-x/y", "package": "evil"},
                                           world=["dev-x/y"]))
    assert whitelist.validate("no-such-cmd", {}) != []


def test_membership_validator_against_world_list():
    assert any("@world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": "dev-x/y"},
                                  world=["app-misc/other"]))
    # cat/pkg comparison: an atom with another version still names the same
    # world member, so the deselect slot is valid
    assert whitelist.validate("emerge-deselect", {"atom": ">=dev-x/y-2"},
                              world=["dev-x/y-1.0"]) == []
    # unreadable world -> fail closed, never "assume member"
    assert any("world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": "dev-x/y"}, world=None))


# --- D3: backup + undo --------------------------------------------------------

def test_world_backup_is_per_run_and_never_overwritten(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])
    dest = whitelist.backup_world("run42", world_file=world)
    assert dest == f"{world}.emerge-ai.run42.bak"
    assert "dev-x/y" in open(dest).read()
    with open(dest, "w") as fh:
        fh.write("MARKER")  # simulate the earlier copy as the truth
    again = whitelist.backup_world("run42", world_file=world)
    assert again == dest and open(dest).read() == "MARKER"


def test_undo_text_is_mechanical():
    assert whitelist.undo_text("emerge-deselect", {"atom": "dev-x/y"}) == \
        "emerge --noreplace dev-x/y"
    text = whitelist.undo_text("emaint-fix-world", {}, backup="/var/lib/portage/world.emerge-ai.r.bak")
    assert "/var/lib/portage/world.emerge-ai.r.bak" in text


# --- executor: ordering, TOCTOU, read-only floor ------------------------------

def test_execute_backups_and_audits_before_running(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])
    audit = tmp_path / "audit.jsonl"
    seen = {}

    def before(argv):  # runs at the exact moment the binary would be invoked
        seen["audit"] = audit_lines(audit)
        seen["backup"] = open(f"{world}.emerge-ai.r1.bak").read()

    calls = []
    res = whitelist.execute("emaint-fix-world", {}, run_id="r1",
                            audit_path=audit, world_file=world,
                            runner=make_runner(calls, before=before))
    assert res["status"] == "executed" and res["returncode"] == 0
    assert [c[0] for c in calls] == [["emaint", "--fix", "world"]]
    assert "dev-x/y" in seen["backup"]  # copy existed before the fix ran
    assert seen["audit"][-1]["decision"] == "command-execute"
    assert seen["audit"][-1]["argv"] == ["emaint", "--fix", "world"]
    assert seen["audit"][-1]["backup"].endswith("r1.bak")
    assert "restore" in seen["audit"][-1]["undo"]
    assert "restore" in res["undo"]


def test_execute_revalidates_at_apply_time(tmp_path, capsys):
    world = world_file(tmp_path, ["dev-x/y"])
    audit = tmp_path / "audit.jsonl"
    calls = []
    res = whitelist.execute("emaint-check-world", {}, runner=make_runner(calls),
                            audit_path=audit)
    assert res["status"] == "executed"
    # read-only: no decision-audit line, no backups — nothing changed
    assert audit_lines(audit) == []
    assert list(tmp_path.glob("*.bak")) == []

    world_file(tmp_path, ["app-misc/gone"])  # parallel run rewrote the world
    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"},
                            runner=make_runner(calls), audit_path=audit,
                            world_file=world)
    assert res["status"] == "rejected" and "@world" in res["reason"]
    # only the earlier read-only check ran — the stale variant never did
    assert [c[0] for c in calls] == [["emaint", "--check", "world"]]
    assert "stale" in capsys.readouterr().out
    assert audit_lines(audit)[-1]["decision"] == "rejected-stale"


def test_execute_rejects_unwritable_audit_before_mutating(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])
    calls = []
    # the audit path is a directory: the append fails -> fail-closed
    res = whitelist.execute("emaint-fix-world", {}, run_id="r9",
                            audit_path=tmp_path,
                            world_file=world, runner=make_runner(calls))
    assert res["status"] == "rejected" and calls == []


def test_backup_failure_aborts_before_argv(tmp_path, capsys):
    calls = []
    res = whitelist.execute("emaint-fix-world", {}, run_id="r1",
                            audit_path=tmp_path / "a.jsonl",
                            world_file=str(tmp_path / "missing-world"),
                            runner=make_runner(calls))
    assert res["status"] == "rejected" and "back up" in res["reason"]
    assert calls == []
