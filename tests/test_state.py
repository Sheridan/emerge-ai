import pytest

from aimerge.flags import Mode
from aimerge.state import (
    INCIDENT,
    MERGE,
    PLAN,
    DONE,
    IllegalTransition,
    latest_incomplete,
    load_run,
    new_run,
    save_run,
    transition,
)


def test_transition_guard(tmp_path):
    run = new_run(["-uDN", "@world"], Mode())
    transition(run, PLAN, runs_dir=tmp_path)
    with pytest.raises(IllegalTransition):
        transition(run, MERGE, runs_dir=tmp_path)
    transition(run, "PROTECT", runs_dir=tmp_path)
    transition(run, MERGE, runs_dir=tmp_path)
    transition(run, INCIDENT, runs_dir=tmp_path)
    transition(run, MERGE, runs_dir=tmp_path)
    transition(run, DONE, runs_dir=tmp_path)
    assert run.complete


def test_persist_and_resume_context(tmp_path):
    run = new_run(["-a", "sys-apps/foo"], Mode(noninteractive=True))
    run.state = PLAN
    save_run(run, runs_dir=tmp_path)
    transition(run, "PROTECT", runs_dir=tmp_path)
    transition(run, MERGE, runs_dir=tmp_path)
    transition(run, INCIDENT, runs_dir=tmp_path)
    run.incident = {"class": "block", "log_tail": "!!! Problem..." , "attempts": 2}
    save_run(run, runs_dir=tmp_path)

    resumed = latest_incomplete(runs_dir=tmp_path)
    assert resumed is not None and resumed.run_id == run.run_id
    assert resumed.incident["class"] == "block"
    assert resumed.mode["noninteractive"] is True

    done = load_run(run.run_id, runs_dir=tmp_path)
    transition(done, MERGE, runs_dir=tmp_path)
    transition(done, DONE, runs_dir=tmp_path)
    assert latest_incomplete(runs_dir=tmp_path) is None


def test_changelog_field_defaults_none_for_old_reports(tmp_path):
    run = new_run(["app-misc/foo"], Mode())
    transition(run, PLAN, runs_dir=tmp_path)
    transition(run, "PROTECT", runs_dir=tmp_path)
    transition(run, MERGE, runs_dir=tmp_path)
    transition(run, DONE, runs_dir=tmp_path)
    path = tmp_path / f"{run.run_id}.json"
    import json
    data = json.loads(path.read_text())
    data.pop("changelog", None)  # simulate a report written before the field existed
    path.write_text(json.dumps(data))
    assert load_run(run.run_id, runs_dir=tmp_path).changelog is None
    run.changelog = "aimerge changelog digest:\n- x"
    save_run(run, runs_dir=tmp_path)
    assert load_run(run.run_id, runs_dir=tmp_path).changelog.startswith("aimerge changelog")
