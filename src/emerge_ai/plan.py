"""Plan phase: resolver output -> typed, tiered queue (spec: run-reporting)."""

from __future__ import annotations

from dataclasses import dataclass, field

from emerge_ai import portage_compat
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


def _iter_installed_tasks(altlist) -> list[str]:
    cpvs = []
    for entry in altlist:
        pkg = getattr(entry, "pkg", None) or getattr(entry, "merge", None)
        if pkg is None:
            pkg = entry if isinstance(entry, str) else getattr(entry, "_pkg", None)
        if pkg is None:
            continue
        cpv = str(pkg)
        if "/" in cpv:
            cpvs.append(cpv)
    return cpvs


def build_plan(
    emerge_args: list[str],
    tier_service,
    *,
    load_config=portage_compat.load_emerge_config,
    resolve=portage_compat.resolve,
    system_atoms: set[str] | None = None,
) -> Plan:
    opts = {"--pretend": True, "--quiet": True, "--nodeps": True}
    args = [a for a in emerge_args if not a.startswith("-")]
    cfg = load_config(action="build", args=args, opts=opts)
    success, graph, _fav = resolve(cfg)
    if not success:
        raise RuntimeError("resolver failed while building plan")
    cpvs = _iter_installed_tasks(graph.altlist())
    system_cps = {package_of(a) for a in (system_atoms or set())}
    entries = []
    for cpv in cpvs:
        cls = tier_service.classify(cpv, in_system_set=package_of(cpv) in system_cps)
        entries.append(PlanEntry(cpv=cpv, tier=cls.tier, tier_source=cls.source))
    return Plan(entries=entries)


def _in_system(cpv: str, system_atoms: set[str] | None) -> bool:
    return package_of(cpv) in {package_of(a) for a in (system_atoms or set())}
