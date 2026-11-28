"""Run state machine with persistence (spec: run-reporting / машина состояний)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from aimerge.flags import Mode

RUNS_DIR = "/var/lib/aimerge/runs"

VERSION_CHECK = "VERSION_CHECK"
PLAN = "PLAN"
PROTECT = "PROTECT"
MERGE = "MERGE"
INCIDENT = "INCIDENT"
CONFIG = "CONFIG"
DIGEST = "DIGEST"
DONE = "DONE"

TRANSITIONS: dict[str, set[str]] = {
    VERSION_CHECK: {PLAN},
    PLAN: {PROTECT, DONE, INCIDENT},
    PROTECT: {MERGE, DONE},
    MERGE: {INCIDENT, DIGEST, DONE},
    INCIDENT: {CONFIG, MERGE, DONE},
    CONFIG: {MERGE, DONE},
    DIGEST: {DONE},
    DONE: set(),
}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class RunState:
    run_id: str
    state: str = VERSION_CHECK
    argv: list = field(default_factory=list)
    mode: dict = field(default_factory=dict)
    plan: list = field(default_factory=list)
    incident: dict | None = None
    protection: dict | None = None
    agent_proposal: str | None = None
    changelog: str | None = None
    rollback: str | None = None  # rollback channel outcome (wire-rollback-channel)
    repair: list = field(default_factory=list)  # applied repair cycles (wire-agent-apply-loop)
    triage: dict | None = None  # plan-phase verdict (spec: plan-triage)
    consent_repairs: list = field(default_factory=list)  # pre-merge consent fixes
    # (spec: consent-dialogue; deliberately not in `repair` — REPAIR_LIMIT
    #  counts the autonomous post-merge loop only)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def complete(self) -> bool:
        return self.state == DONE


def new_run(argv: list[str], mode: Mode) -> RunState:
    return RunState(
        run_id=uuid.uuid4().hex[:12],
        argv=list(argv),
        mode=asdict(mode),
    )


def transition(run: RunState, new_state: str, runs_dir: str | Path = RUNS_DIR) -> RunState:
    if new_state not in TRANSITIONS.get(run.state, set()):
        raise IllegalTransition(f"{run.state} -> {new_state}")
    run.state = new_state
    save_run(run, runs_dir)
    return run


def plan_artifact_path(run: RunState, runs_dir: str | Path = RUNS_DIR) -> str:
    """Where the full plan-phase text lives (spec: plan-triage, design D4): a
    per-run subdirectory next to the flat state JSON; the state layout of
    runs_dir itself is untouched."""
    return str(Path(runs_dir) / run.run_id / "plan-output.txt")


def save_run(run: RunState, runs_dir: str | Path = RUNS_DIR) -> Path:
    d = Path(runs_dir)
    d.mkdir(parents=True, exist_ok=True)
    run.updated = time.time()
    path = d / f"{run.run_id}.json"
    path.write_text(json.dumps(asdict(run), ensure_ascii=False, indent=1))
    return path


def load_run(run_id: str, runs_dir: str | Path = RUNS_DIR) -> RunState:
    data = json.loads((Path(runs_dir) / f"{run_id}.json").read_text())
    return RunState(**data)


def latest_incomplete(runs_dir: str | Path = RUNS_DIR) -> RunState | None:
    d = Path(runs_dir)
    if not d.exists():
        return None
    runs = []
    for p in d.glob("*.json"):
        try:
            run = RunState(**json.loads(p.read_text()))
        except (json.JSONDecodeError, TypeError):
            continue
        if not run.complete:
            runs.append(run)
    if not runs:
        return None
    return max(runs, key=lambda r: r.updated)
