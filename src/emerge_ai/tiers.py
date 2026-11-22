"""Risk-tier service: deterministic hints -> LLM classification -> cache -> fallback.

Single source of truth for tiers, consumed by consent gate, snapshot trigger,
autonomy matrix and doctor (spec: risk-tiers).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from emerge_ai.llm import LLMError

CACHE_PATH = "/var/lib/emerge-ai/tiers.json"

# Only unambiguous, nomenclature-core entries; the LLM handles the long tail.
DEFAULT_HINTS: dict[str, int] = {
    "sys-kernel/gentoo-sources": 1,
    "sys-kernel/vanilla-sources": 1,
    "sys-libs/glibc": 1,
    "sys-apps/baselayout": 1,
    "sys-apps/openrc": 1,
    "sys-apps/systemd": 1,
    "sys-boot/grub": 1,
    "sys-apps/busybox": 1,
    "app-shells/bash": 2,
    "sys-apps/coreutils": 2,
    "sys-apps/util-linux": 2,
    "sys-apps/findutils": 2,
    "app-arch/tar": 2,
    "sys-libs/pam": 2,
    "sys-libs/shadow": 2,
    "net-misc/openssh": 3,
    "x11-base/xorg-server": 4,
    "x11-base/xorg-drivers": 4,
}

CLASSIFY_SYSTEM = (
    "You classify Gentoo packages into risk tiers: "
    "1 can make the host unbootable; 2 can break shell login; "
    "3 can break network/ssh login; 4 can break graphical login; 5 everything else. "
    "Answer ONLY JSON: {\"tier\": <int 1-5>, \"reason\": \"<short>\"}. "
    "When unsure between tiers, answer the lower number."
)


@dataclass
class Classification:
    cp: str
    tier: int
    source: str  # hint | cache | llm | fallback
    reason: str = ""


def package_of(atom_or_cpv: str) -> str:
    a = re.sub(r"^[<>=~]*", "", atom_or_cpv)
    a = re.split(r"[-](\d|[A-Za-z]*\d)", a)[0] if "/" in a else a
    a = a.split(":")[0]
    parts = a.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else a


class TierService:
    def __init__(
        self,
        client=None,
        cache_path: str | Path | None = CACHE_PATH,
        hints: dict[str, int] | None = None,
    ):
        self.client = client
        self.hints = DEFAULT_HINTS if hints is None else hints
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict | None = None

    def _load(self) -> dict:
        if self._cache is None:
            if self.cache_path and self.cache_path.exists():
                try:
                    self._cache = json.loads(self.cache_path.read_text())
                except json.JSONDecodeError:
                    self._cache = {}
            else:
                self._cache = {}
        return self._cache

    def _store(self, cp: str, tier: int, reason: str) -> None:
        cache = self._load()
        cache[cp] = {"tier": tier, "reason": reason}
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))

    def classify(self, atom_or_cpv: str, in_system_set: bool = False) -> Classification:
        cp = package_of(atom_or_cpv)
        if cp in self.hints:
            return Classification(cp, self.hints[cp], "hint", "deterministic nomenclature")
        entry = self._load().get(cp)
        if isinstance(entry, dict) and 1 <= entry.get("tier", 0) <= 5:
            return Classification(cp, entry["tier"], "cache", entry.get("reason", ""))
        if self.client is None:
            return self._fallback(cp, "no LLM client")
        hint = " Package is a member of @system." if in_system_set else ""
        try:
            resp = self.client.chat(
                [
                    {"role": "system", "content": CLASSIFY_SYSTEM},
                    {"role": "user", "content": f"Classify package: {cp}.{hint}"},
                ]
            )
        except LLMError as exc:
            return self._fallback(cp, f"LLM unavailable: {exc}")
        parsed = _parse_tier_json(resp.content)
        if parsed is None:
            return self._fallback(cp, "unparseable model answer")
        tier, reason = parsed
        self._store(cp, tier, reason)
        return Classification(cp, tier, "llm", reason)

    @staticmethod
    def _fallback(cp: str, reason: str) -> Classification:
        return Classification(cp, 1, "fallback", f"conservative default: {reason}")


def _parse_tier_json(text: str) -> tuple[int, str] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    tier = data.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 5:
        return None
    return tier, str(data.get("reason", ""))


# ------------------- consumer helpers (spec: single source of truth) -----------


def distribution(classifications) -> Counter:
    return Counter(c.tier for c in classifications)


def most_critical(classifications) -> int:
    return min(c.tier for c in classifications)


def snapshot_required(classifications) -> bool:
    """One btrfs snapshot per run iff any queued package is tier 1-4."""
    return any(c.tier <= 4 for c in classifications)


def noninteractive_auto_allowed(classification: Classification) -> bool:
    """--noninteractive autonomy: only rest-tier without responsibility flag."""
    return classification.tier == 5
