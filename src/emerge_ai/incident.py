"""Failure detection: emerge stderr/exit -> incident classes (spec: failure-taxonomy).

Class table is ordered; first match wins. Phases come from the Portage build
log path (/var/tmp/portage/<cpv>/temp/<phase>.log)."""

from __future__ import annotations

import re

FAILURE_CLASSES: list[tuple[str, list[str]]] = [
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


def classify(stderr_text: str) -> str:
    for name, patterns in FAILURE_CLASSES:
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
    returncode: int, stderr_text: str, argv: list[str], tail_chars: int = 4000
) -> dict:
    klass = classify(stderr_text)
    cpv = extract_cpv(stderr_text)
    phase = extract_phase(stderr_text, klass)
    incident = {
        "class": klass,
        "returncode": returncode,
        "argv": list(argv),
        "stderr_tail": stderr_text[-tail_chars:],
        "phase": phase,
    }
    if cpv:
        incident["cpv"] = cpv
        log_match = PHASE_RE.search(stderr_text)
        incident["build_log"] = (
            log_match.group(0) if log_match else f"/var/tmp/portage/{cpv}/temp/build.log"
        )
    return incident
