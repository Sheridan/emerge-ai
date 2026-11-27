"""Plan-phase triage: deterministic severity scan of the emerge --pretend text
(spec: plan-triage, design D1). No LLM is consulted here: the clean/degraded
verdict and the findings must exist on a host without an endpoint. The scan is
an O(n) regex pass over the already-buffered ANSI-stripped text, run after the
plan phase — the byte-for-byte streaming pumps are deliberately untouched.

The marker vocabulary is the single place to extend (design D7 risk): severity
channels of portage (!!! / WARNING: / " * IMPORTANT:") plus structural
evidence lines (conflicts with / required by / masked by:) plus the shape flag
(update requested, Total: 0 packages)."""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field

from emerge_ai import ui
from emerge_ai.runner import flag_present

CLEAN = "clean"
DEGRADED = "degraded"

# cap of the severity slice sent to the LLM (design D2: a few KB, not the whole
# pretend output of @world -av)
SLICE_CAP_BYTES = 4096
CONTEXT = 2  # context lines around every marker line in the slice
MAX_EVIDENCE_CHARS = 300

# incident.CPV_RE stops at revisions and slots, but the resolver speaks in
# dependency atoms: dev-libs/jemalloc-5.4.0-r2:0/0::gentoo, >=a/b-1.2.3:0/0=
ATOM_RE = re.compile(
    r"(?<![\w/.-])([a-z][a-z0-9+_.-]*/[A-Za-z][A-Za-z0-9+_.-]*-\d[\w.]*-r\d+)"
    r"|(?<![\w/.-])([a-z][a-z0-9+_.-]*/[A-Za-z][A-Za-z0-9+_.-]*-\d[\w.]*)"
)
# bare cat/pkg only when the whole line is the atom ("app-container/edk2-bin:0")
# — otherwise English compounds like "updates/rebuilds" would read as atoms
BARE_ATOM_RE = re.compile(
    r"^\s*(?:[<>]=?)?([a-z][a-z0-9+_.-]*/[A-Za-z][A-Za-z0-9+_.-]*)(?::[^\s]+)?\s*$")

WORLD_FILE_RE = re.compile(r"Problems have been detected with your world file")
SKIPPED_RE = re.compile(r"skipped due to")
CONFLICT_RE = re.compile(r"conflicts with")
MASKED_BY_RE = re.compile(r"masked by:")
REQUIRED_BY_RE = re.compile(r"required by")
CONFIG_UPDATING_RE = re.compile(r"IMPORTANT:.*?config file\s+'([^']+)'[^.]*needs updating")
SEVERITY_RE = re.compile(r"^\s*!!!")
WARNING_RE = re.compile(r"^\s*WARNING:")
IMPORTANT_RE = re.compile(r"^\s*\*\s*IMPORTANT:")
TOTAL_LINE_RE = re.compile(r"^\s*Total:\s*(\d+)\s+packages")

UPDATE_FLAGS = ("-u", "-D", "-N", "--update", "--deep", "--newuse")

LINE_LIMIT = 200_000  # defensive cap for absurd inputs; scan stays linear


@dataclass
class Finding:
    kind: str
    cpv: str | None
    evidence: str
    line_no: int


@dataclass
class Verdict:
    status: str  # CLEAN | DEGRADED
    findings: list[Finding] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.status == DEGRADED

    def to_dict(self) -> dict:
        return {"status": self.status, "findings": [asdict(f) for f in self.findings]}


def _atom_of(line: str) -> str | None:
    """The dependency atom named on the line, versioned first (with -rN),
    bare cat/pkg as the fallback; slots and repo suffixes are not captured."""
    m = ATOM_RE.search(line)
    if m:
        return m.group(1) or m.group(2)
    m = BARE_ATOM_RE.search(line)
    return m.group(1) if m else None


def _kind_of(line: str) -> str | None:
    """Ordered per-line classifier: the first matching channel wins (one
    finding per line, like the FAILURE_CLASSES table in incident.py)."""
    if CONFIG_UPDATING_RE.search(line):
        return "config-updating"
    if WORLD_FILE_RE.search(line):
        return "world-file"
    if WARNING_RE.search(line) and SKIPPED_RE.search(line):
        return "dep-conflict"
    if CONFLICT_RE.search(line):
        return "conflict"
    if MASKED_BY_RE.search(line):
        return "masked"
    if REQUIRED_BY_RE.search(line):
        return "dep-required"
    if SEVERITY_RE.search(line):
        return "severity"
    if IMPORTANT_RE.search(line):
        return "important"
    if WARNING_RE.search(line):
        return "warning"
    return None


def parse_total(text: str) -> int | None:
    """N from the `Total: N packages` summary line (plan.py parses the same
    region via digest.EBUILD_LINE_RE)."""
    for line in text.splitlines()[:LINE_LIMIT]:
        m = TOTAL_LINE_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def requests_update(argv: list[str] | None) -> bool:
    """An update request (-u/-D/-N, clusters included) shapes the empty-plan
    flag: Total: 0 packages then means nothing merged, not nothing to do."""
    return bool(argv) and flag_present(list(argv), UPDATE_FLAGS)


def scan(text: str, argv: list[str] | None = None) -> Verdict:
    """Deterministic verdict of the plan phase at rc == 0."""
    plain = ui.strip_ansi(text or "")
    lines = plain.splitlines()[:LINE_LIMIT]
    findings: list[Finding] = []
    total_line_no = None
    total_n: int | None = None
    for i, line in enumerate(lines):
        m_total = TOTAL_LINE_RE.match(line)
        if m_total:
            total_line_no = i
            total_n = int(m_total.group(1))
            continue
        kind = _kind_of(line)
        if kind is None:
            continue
        cpv = _atom_of(line)
        if cpv is None and kind == "dep-conflict" and i + 1 < len(lines):
            # portage names the skipped package on the line after the WARNING
            cpv = _atom_of(lines[i + 1])
        findings.append(
            Finding(kind, cpv, line.strip()[:MAX_EVIDENCE_CHARS], i)
        )
    if total_n == 0 and requests_update(argv) and total_line_no is not None:
        findings.append(
            Finding("empty-update", None,
                    f"update requested ({' '.join(a for a in (argv or []) if a.startswith('-'))}), "
                    f"but plan is empty: {lines[total_line_no].strip()}",
                    total_line_no)
        )
    return Verdict(DEGRADED if findings else CLEAN, findings)


def build_slice(text: str, cap_bytes: int = SLICE_CAP_BYTES, path: str | None = None) -> str:
    """Severity slice for the LLM prompt (design D2): marker lines with a
    context window, overlapping windows merged, the Total: line kept; USE
    listings outside problem blocks never enter. A cap banner with the artifact
    path closes the slice when the cap is exceeded."""
    plain = ui.strip_ansi(text or "")
    lines = plain.splitlines()[:LINE_LIMIT]
    keep: list[tuple[int, int]] = []
    total_idx: int | None = None
    for i, line in enumerate(lines):
        if TOTAL_LINE_RE.match(line):
            total_idx = i
        if _kind_of(line) is not None:
            keep.append((max(0, i - CONTEXT), min(len(lines) - 1, i + CONTEXT)))
    if not keep or not lines:
        return ""
    if total_idx is not None:
        keep.append((max(0, total_idx - CONTEXT), min(len(lines) - 1, total_idx + CONTEXT)))
    keep.sort()
    merged: list[list[int]] = [list(keep[0])]
    for start, end in keep[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    banner = f"\n[capped; полный текст: {path}]" if path else "\n[capped]"
    budget = max(0, cap_bytes - len(banner.encode("utf-8")))
    parts: list[str] = []
    used = 0
    capped = False
    for start, end in merged:
        block = "\n".join(lines[start : end + 1])
        cost = len(block.encode("utf-8")) + (1 if parts else 0)
        if used + cost > budget:
            capped = True
            break
        parts.append(block)
        used += cost
    if not parts:
        # even one oversized block enters as a capped head, never as nothing
        head = "\n".join(lines[merged[0][0] : merged[0][1] + 1])
        head = head.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
        return head + banner
    return "\n...\n".join(parts) + (banner if capped else "")


def plan_incident(argv: list[str], verdict: Verdict, severity_slice: str = "",
                  log_path: str | None = None) -> dict:
    """Incident for the plan-degraded class (design D4): the capped slice is
    the inline evidence, the full text is referenced through log_path — never
    a stderr_tail truncation and never the full text riding into the prompt."""
    return {
        "class": "plan-degraded",
        "returncode": 0,
        "argv": list(argv),
        "phase": "resolver",
        "stderr_tail": severity_slice,
        "log_path": log_path,
        "findings": [asdict(f) for f in verdict.findings],
    }


_KEYWORD_RE = re.compile(r"(~[A-Za-z0-9_.-]+)")


def _cat_pkg(atom: str) -> str:
    """cat/pkg key of an atom — tiers.package_of, the same comparison key the
    tier machinery and the whitelist use for @world membership."""
    from emerge_ai.tiers import package_of

    return package_of(atom)


def candidates(findings: list[Finding], *, world: list[str] | None = None) -> list[dict]:
    """Fix candidates split by what the apply channel can execute (spec:
    repair-actions): config_edit kinds, the etcupdate channel and the
    whitelisted commands (emaint world fix, emerge --deselect). A deselect is
    executable only for an atom that is a member of @world — pass `world` to
    check it; without the list the variant stays advice (the menu never shows
    a stale entry). Truly uncovered kinds remain advice lines."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, text: str, executable: bool, **extra) -> None:
        if text not in seen:
            seen.add(text)
            out.append({"kind": kind, "text": text, "executable": executable, **extra})

    for f in findings:
        if f.kind == "masked":
            kw = _KEYWORD_RE.search(f.evidence)
            if f.cpv and kw and "keyword" in f.evidence:
                add("accept_keywords", f"={f.cpv} {kw.group(1)}", True)
            else:
                add("mask", f"review the mask hiding {f.cpv or 'the candidate'}", False)
        elif f.kind == "config-updating":
            m = CONFIG_UPDATING_RE.search(f.evidence)
            path = m.group(1) if m else None
            add("etc-update",
                f"resolve the pending config update for {path or 'a config file'}",
                True, **({"path": path} if path else {}))
        elif f.kind == "world-file":
            add("emaint", "repair the world file (emaint --fix world)", True)
        elif f.kind in ("dep-conflict", "conflict"):
            kw = _KEYWORD_RE.search(f.evidence)
            if f.cpv and kw and "keyword" in f.evidence:
                add("accept_keywords", f"={f.cpv} {kw.group(1)}", True)
            if f.cpv:
                in_world = world is not None and any(
                    _cat_pkg(e) == _cat_pkg(f.cpv) for e in world)
                add("deselect",
                    f"remove {f.cpv} from the world set (emerge --deselect {f.cpv})",
                    in_world, atom=f.cpv)
                if not in_world:
                    add("world-review",
                        f"review the conflict around {f.cpv} "
                        "(keyword/use change or deselect)",
                        False)
            else:
                add("world-review",
                    "review the conflict (keyword/use change or deselect)",
                    False)
    return out


def render_report(verdict: Verdict | None, plan_output: str | None = None,
                  for_pretend: bool = False,
                  world: list[str] | None = None, stream=None) -> list[str]:
    """The advisory report shared by --pretend and the mutation modes (D6):
    what happened, what will NOT be merged, candidate whitelist actions; never
    a question, never an action. `world` is the same membership list the
    consent menu validates with, so report and menu agree on what is
    executable. Finding-kind tags get the fixed importance colors (design D4);
    `stream` only decides coloring and must match the stream the lines are
    printed to (design D3)."""
    if verdict is None or not verdict.degraded:
        return []
    stream = sys.stdout if stream is None else stream
    lines = [
        f"emerge-ai plan triage: plan DEGRADED despite exit code 0 "
        f"({len(verdict.findings)} finding(s)) — these packages will NOT be merged:"
    ]
    for f in verdict.findings:
        target = f" {f.cpv}" if f.cpv else ""
        tag = ui.paint(stream, ui.kind_sgr(f.kind), f"[{f.kind}]")
        lines.append(f"  {tag} line {f.line_no + 1}:{target} {f.evidence}")
    cands = candidates(verdict.findings, world=world)
    executable = [c for c in cands if c["executable"]]
    blocked = [c for c in cands if not c["executable"]]
    if executable:
        lines.append("candidate fixes (whitelist actions emerge-ai knows):")
        for c in executable:
            note = " — executed when the run is not --pretend" if for_pretend else ""
            lines.append(f"  + {c['kind']}: {c['text']}{note}")
    if blocked:
        lines.append("repairs emerge-ai cannot execute yet (manual guidance):")
        for c in blocked:
            lines.append(f"  - {c['kind']}: {c['text']} (not executable by emerge-ai yet)")
    if plan_output:
        lines.append(f"full plan output: {plan_output}")
    return lines
