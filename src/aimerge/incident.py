"""Failure detection: emerge stderr/exit -> incident classes (spec: failure-taxonomy).

Class table is ordered; first match wins. Phases come from the Portage build
log path (/var/tmp/portage/<cpv>/temp/<phase>.log)."""

from __future__ import annotations

import re

from aimerge import ui

FAILURE_CLASSES: list[tuple[str, list[str]]] = [
    ("plan-degraded", [
        r"Problems have been detected with your world file",
        r"WARNING:.*skipped due to",
    ]),
    ("cycle", [
        r"Dependency loop #\d+",
        r"circular dependenc",
        r"Total length: \[\d+\]",
    ]),
    ("sandbox", [
        r"SANDBOX VIOLATION",
        r"sandbox:.*(?:not allowed|denied|access)",
        r"sandbox: The call .* was blocked",
        r"sandbox: Popen is not allowed",
    ]),
    ("config-protect", [
        r"collision-protect",
        r"Protected config file",
        r"etc-update.*protect",
        r"--- !mtime-overlay-protected",
    ]),
    ("license", [
        r"unaccepted licenses?",
        r"licenses? must be accepted",
        r"ACCEPT_LICENSES",
        r"license\(s\) must be agreed to",
    ]),
    ("keywords", [
        r"unsupported KEYWORDS",
        r"not keyworded",
        r"ACCEPT_KEYWORDS",
        r"marked as stable",
    ]),
    ("use", [
        r"REQUIRED_USE",
        r"USE requirements?.*(?:cannot be satisfied|not satisfied)",
        r"Unsatisfiable dependencies.*USE",
        r"required by the USE",
    ]),
    ("mask", [
        r"\bis masked\b",
        r"masked by:",
        r"package\.mask",
        r"are hard-masked",
        r"hard-masked",
    ]),
    ("blocks", [
        r"blocker",
        r"!!! Problem resolving dependencies",
        r"there are no ebuilds to satisfy",
        r"conflicts with",
    ]),
    ("fetch", [
        r"VERIFY FAILED",
        r"Download failed",
        r"Could not fetch",
        r"Unable to (?:download|resume)",
        r"Size of None does not match",
        r"missing digests",
    ]),
    ("compile", [
        r"failed \((?:compile|test|install|configure) phase\)",
        r"Compile failure",
        r"emake failed",
        r" * Build failure",
        r">>> Failed",
    ]),
]

CPV_RE = re.compile(r"(?<![\w/.-])([a-z][a-z0-9+_.-]*/[A-Za-z][A-Za-z0-9+_.-]*?-\d[\w.]*[a-z]?)(?![-\w.])")
PHASE_RE = re.compile(r"/var/tmp/portage/([\w+.-]+/[\w.-]+?-\d[\w.]*[a-z]?)/temp/(\w+)\.log")
PHASE_MSG_RE = re.compile(r"failed \((\w+) phase\)")

FALLBACK = "unknown"


def classify(stderr_text: str, exclude: frozenset = frozenset()) -> str:
    for name, patterns in FAILURE_CLASSES:
        if name in exclude:
            continue
        for pat in patterns:
            if re.search(pat, stderr_text, re.IGNORECASE if name != "sandbox" else 0):
                return name
    return FALLBACK


def extract_cpv(text: str) -> str | None:
    m = PHASE_RE.search(text)
    if m:
        return m.group(1)
    m = CPV_RE.search(text)
    return m.group(1) if m else None


def extract_phase(text: str, klass: str) -> str | None:
    m = PHASE_MSG_RE.search(text)
    if m:
        return m.group(1)
    m = PHASE_RE.search(text)
    if m and m.group(2) not in ("build", "environ", "logging"):
        return m.group(2)
    if klass in ("compile", "sandbox"):
        return "compile"
    if klass == "fetch":
        return "fetch"
    return "resolver" if klass not in ("unknown",) else None


def build_incident(
    returncode: int, stderr_text: str, argv: list[str], tail_chars: int = 4000,
    log_path: str | None = None,
) -> dict:
    text = ui.strip_ansi(stderr_text)
    klass = classify(text)
    if klass == "plan-degraded" and returncode != 0:
        # plan-degraded is the rc==0 verdict (spec: plan-triage); a non-zero
        # run showing the same evidence lines keeps its structural class
        klass = classify(text, exclude=frozenset({"plan-degraded"}))
    cpv = extract_cpv(text)
    phase = extract_phase(text, klass)
    incident = {
        "class": klass,
        "returncode": returncode,
        "argv": list(argv),
        "stderr_tail": text[-tail_chars:],
        "phase": phase,
    }
    if klass == "plan-degraded":
        # plan-triage D4: the degraded-plan incident references the full run
        # artifact; the stderr_tail truncation is not applied to this class
        incident["stderr_tail"] = text
        if log_path:
            incident["log_path"] = log_path
    if cpv:
        incident["cpv"] = cpv
        log_match = PHASE_RE.search(text)
        incident["build_log"] = (
            log_match.group(0) if log_match else f"/var/tmp/portage/{cpv}/temp/build.log"
        )
    return incident
