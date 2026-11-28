"""Whitelisted commands (spec: repair-actions) — closed registry, slot
validation, TOCTOU re-check, backup, pre-execution audit ordering."""

import json
import os
import pathlib

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
    assert whitelist.render_argv("emerge-deselect", {"atom": "sys-devel/gcc:14"},
                                 binaries={"emerge": "/usr/local/bin/emerge"}) == \
        ["/usr/local/bin/emerge", "--deselect", "sys-devel/gcc:14"]


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
    # a versioned world line passes verbatim, slot and repo included
    assert whitelist.validate("emerge-deselect", {"atom": "=dev-x/y-1.0:0::repo"},
                              world=["=dev-x/y-1.0:0::repo"]) == []


def test_atom_form_requires_an_operator_before_a_version():
    # spec: repair-actions — "cat/pkg-1.2.3" is a cpv, not an atom: that exact
    # shape made emerge print "is not a package atom" (rc 1) at execution time
    errors = whitelist.validate("emerge-deselect", {"atom": "dev-x/y-1.0"},
                                world=["dev-x/y-1.0"])
    assert any("not a package atom" in e for e in errors)
    # every portage operator carries a version; the bare form carries a slot
    for ok in ["=dev-x/y-1.0", ">=dev-x/y-1.0", "<=dev-x/y-1.0-r1", "~dev-x/y-1.0",
               "~>dev-x/y-1.0", "<dev-x/y-1.0", ">dev-x/y-1.0", "dev-x/y",
               "dev-x/y:14", "dev-x/y:0::repo"]:
        assert whitelist.validate("emerge-deselect", {"atom": ok}, world=[ok]) == [], ok
    for bad_form in ["=dev-x/y", "~dev-x/y", "dev-x/y-1.0", ">=dev-x/y"]:
        assert any("not a package atom" in e
                   for e in whitelist.validate("emerge-deselect", {"atom": bad_form},
                                               world=[bad_form])), bad_form


def test_slots_shape_is_enforced():
    assert any("missing slot" in e
               for e in whitelist.validate("emerge-deselect", {}, world=[]))
    assert any("not part of" in e
               for e in whitelist.validate("emerge-deselect",
                                           {"atom": "dev-x/y", "package": "evil"},
                                           world=["dev-x/y"]))
    assert whitelist.validate("no-such-cmd", {}) != []


def test_membership_validator_against_world_list():
    # membership is the world line VERBATIM, not a cat/pkg match (design D2)
    assert whitelist.validate("emerge-deselect", {"atom": "dev-x/y"},
                              world=["dev-x/y"]) == []
    assert any("@world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": "dev-x/y"},
                                  world=["app-misc/other"]))
    assert whitelist.validate("emerge-deselect", {"atom": "dev-x/y:14"},
                              world=["dev-x/y:14"]) == []
    # the same cat/pkg is not enough: the line must be the line
    assert any("@world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": "dev-x/y"},
                                  world=["dev-x/y:14"]))
    assert any("@world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": "dev-x/y:14"},
                                  world=["dev-x/y"]))
    # the previously accepted "nearly right" form — an operator atom matching
    # nothing in the file, emerge exiting 0 on 'No matching atoms' — is gone
    assert any("@world" in e for e in
               whitelist.validate("emerge-deselect", {"atom": ">=dev-x/y-2"},
                                  world=["=dev-x/y-1.0"]))
    assert whitelist.validate("emerge-deselect", {"atom": "=dev-x/y-1.0"},
                              world=["=dev-x/y-1.0"]) == []
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


def test_execute_announces_full_argv(tmp_path, capsys):
    # spec: progress-logging — the whitelisted argv is announced before it runs
    world = world_file(tmp_path, ["dev-x/y"])
    calls = []
    res = whitelist.execute("emaint-fix-world", {}, run_id="r1",
                            audit_path=tmp_path / "audit.jsonl", world_file=world,
                            runner=make_runner(calls))
    assert res["status"] == "executed"
    assert "emerge-ai: running: emaint --fix world" in capsys.readouterr().err


def test_rejected_execution_is_not_announced(tmp_path, capsys):
    res = whitelist.execute("rm-rf-everything", {}, runner=lambda *a, **k: Proc())
    assert res["status"] == "rejected"
    assert "emerge-ai: running" not in capsys.readouterr().err


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


def test_execute_rejects_a_rewritten_world_line(tmp_path):
    # the file line gained a slot since the menu was built — exact membership
    # in the TOCTOU re-check catches a rewritten line, not only a removed one
    world = world_file(tmp_path, ["dev-x/y:14"])
    calls = []
    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"}, run_id="r1",
                            runner=make_runner(calls),
                            audit_path=tmp_path / "a.jsonl", world_file=world)
    assert res["status"] == "rejected" and "@world" in res["reason"]
    assert calls == []
    assert pathlib.Path(world).read_text() == "dev-x/y:14\n"


# --- effect check: verify "world-entry-removed" -------------------------------

def test_deselect_no_effect_is_honest_when_the_line_stays(tmp_path):
    # portage prints 'No matching atoms found in "world"' and exits 0 —
    # the file, not the rc, says whether anything was fixed
    world = world_file(tmp_path, ["dev-x/y"])
    audit = tmp_path / "audit.jsonl"
    msgs = []
    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"},
                            runner=make_runner([], stdout='>>> No matching atoms found\n'),
                            audit_path=audit, world_file=world, echo=msgs.append)
    assert res["status"] == "no-effect" and res["changed"] is False
    recs = audit_lines(audit)
    assert recs[-1]["decision"] == "command-effect"
    assert recs[-1]["changed"] is False and recs[-1]["returncode"] == 0
    assert recs[-2]["decision"] == "command-execute"  # audit-before-mutation kept
    assert any("no effect" in m and "emerge --deselect dev-x/y" in m for m in msgs)


def test_deselect_effect_true_when_the_line_leaves_the_world(tmp_path):
    world = world_file(tmp_path, ["dev-x/y", "app-misc/keep"])
    audit = tmp_path / "audit.jsonl"

    def runner(argv, **kwargs):  # a real deselect rewrites the favorites file
        with open(world, "w") as fh:
            fh.write("app-misc/keep\n")
        return Proc(stdout='>>> Removing dev-x/y from "world" favorites file...\n')

    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"}, runner=runner,
                            audit_path=audit, world_file=world)
    assert res["status"] == "executed" and res["changed"] is True
    assert audit_lines(audit)[-1]["decision"] == "command-effect"
    assert audit_lines(audit)[-1]["changed"] is True


def test_deselect_failed_command_is_no_effect(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])
    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"},
                            runner=make_runner([], rc=1),
                            audit_path=tmp_path / "a.jsonl", world_file=world,
                            echo=lambda m: None)
    assert res["status"] == "no-effect" and res["changed"] is False


def test_deselect_effect_unknown_when_world_unreadable(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])

    def runner(argv, **kwargs):
        os.remove(world)
        os.mkdir(world)  # the file cannot be re-read after the run
        return Proc()

    res = whitelist.execute("emerge-deselect", {"atom": "dev-x/y"}, runner=runner,
                            audit_path=tmp_path / "a.jsonl", world_file=world,
                            echo=lambda m: None)
    assert res["status"] == "no-effect" and res["changed"] is None


def test_commands_without_verify_have_no_changed_field(tmp_path):
    world = world_file(tmp_path, ["dev-x/y"])
    calls = []
    res = whitelist.execute("emaint-fix-world", {}, run_id="r1",
                            audit_path=tmp_path / "a.jsonl", world_file=world,
                            runner=make_runner(calls))
    assert res["status"] == "executed" and "changed" not in res
    res = whitelist.execute("emaint-check-world", {}, runner=make_runner(calls),
                            audit_path=tmp_path / "a.jsonl")
    assert res["status"] == "executed" and "changed" not in res
