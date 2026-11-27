"""Plan phase: resolver output -> typed, tiered queue (spec: run-reporting)."""

from __future__ import annotations

from dataclasses import dataclass, field

from emerge_ai import portage_compat, ui
from emerge_ai.digest import EBUILD_LINE_RE
from emerge_ai.tiers import Classification, distribution, package_of


@dataclass
class PlanEntry:
    cpv: str
    tier: int
    tier_source: str


@dataclass
class Plan:
    entries: list[PlanEntry] = field(default_factory=list)

    @property
    def distribution(self):
        return distribution([Classification(e.cpv, e.tier, e.tier_source) for e in self.entries])


def build_plan(
    emerge_args: list[str],
    tier_service,
    *,
    parse_opts=portage_compat.parse_emerge_opts,
    load_config=portage_compat.load_emerge_config,
    resolve=portage_compat.resolve,
    system_atoms: set[str] | None = None,
) -> Plan:
    """Fallback queue from a resolver run over the user's own argv (spec:
    run-reporting, design D2/D3). The old `--nodeps`/atom-only call was not an
    honest seam: its altlist was the whole set closure (every entry
    'merge'), not what emerge would merge. Parsing the argv through
    `_emerge.main.parse_opts` and forcing --pretend reproduces emerge's own
    resolution; the queue is the altlist minus already-installed entries."""
    action, opts, files = parse_opts(list(emerge_args))
    opts["--pretend"] = True
    opts["--quiet"] = True
    opts.pop("--ask", None)  # a resolver must never ask (cli drops it too)
    cfg = load_config(action=action, args=files, opts=opts)
    success, graph, _fav = resolve(cfg)
    if not success:
        raise RuntimeError("resolver failed while building plan")
    cpvs = portage_compat.queued_cpvs(graph)
    system_cps = {package_of(a) for a in (system_atoms or set())}
    entries = []
    for cpv in cpvs:
        cls = tier_service.classify(cpv, in_system_set=package_of(cpv) in system_cps)
        entries.append(PlanEntry(cpv=cpv, tier=cls.tier, tier_source=cls.source))
    return Plan(entries=entries)


def _in_system(cpv: str, system_atoms: set[str] | None) -> bool:
    return package_of(cpv) in {package_of(a) for a in (system_atoms or set())}


def _clean_cpv(raw: str) -> str | None:
    """`[sys-libs/zlib-1.3.1:0/1::gentoo]` / `dev-libs/foo-1.2.3  USE=...` -> CPV."""
    token = raw.strip().strip("[]")
    if not token:
        return None
    token = token.split("::")[0].split(":")[0]
    if "/" not in token or not any(c.isdigit() for c in token):
        return None
    return token


def build_plan_from_output(
    output: str,
    emerge_args: list[str],
    tier_service,
    *,
    fallback=build_plan,
    system_atoms: set[str] | None = None,
) -> Plan:
    """Build the merge queue from the already-captured `--pretend` output
    (avoid-double-resolve-in-plan): the plan phase runs emerge --pretend for
    its verbatim display, re-parsing that text avoids a second full resolve.
    Unparseable output (quiet formats, unexpected layouts) falls back to the
    resolver-based build_plan — identical behavior, one resolve later."""
    plain = ui.strip_ansi(output)
    cpvs: list[str] = []
    for m in EBUILD_LINE_RE.finditer(plain):
        cpv = _clean_cpv(m.group(1))
        if cpv and cpv not in cpvs:
            cpvs.append(cpv)
    if not cpvs:
        return fallback(emerge_args, tier_service)
    system_cps = {package_of(a) for a in (system_atoms or set())}
    entries = []
    for cpv in cpvs:
        cls = tier_service.classify(cpv, in_system_set=package_of(cpv) in system_cps)
        entries.append(PlanEntry(cpv=cpv, tier=cls.tier, tier_source=cls.source))
    return Plan(entries=entries)
