import json

import pytest

from emerge_ai.llm import LLMError, Response
from emerge_ai.tiers import (
    TierService,
    distribution,
    most_critical,
    noninteractive_auto_allowed,
    package_of,
    snapshot_required,
)
from emerge_ai.tiers import Classification


class FakeClient:
    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = 0
        self.last_messages = None

    def chat(self, messages, tools=None, temperature=0.2):
        self.calls += 1
        self.last_messages = messages
        if self.error:
            raise self.error
        return Response(content=self.answer)


@pytest.mark.parametrize(
    ("atom", "cp"),
    [
        ("sys-libs/glibc", "sys-libs/glibc"),
        ("sys-libs/glibc-2.42", "sys-libs/glibc"),
        (">=dev-libs/openssl-3.0.15:0/3", "dev-libs/openssl"),
        ("sys-kernel/gentoo-sources-6.6.87", "sys-kernel/gentoo-sources"),
        ("app-editors/vim", "app-editors/vim"),
    ],
)
def test_package_of(atom, cp):
    assert package_of(atom) == cp


def test_hint_beats_llm(tmp_path):
    fake = FakeClient('{"tier": 4}')
    svc = TierService(fake, cache_path=tmp_path / "tiers.json")
    c = svc.classify("sys-libs/glibc-2.42")
    assert (c.tier, c.source) == (1, "hint")
    assert fake.calls == 0


def test_llm_classification_cached(tmp_path):
    cache = tmp_path / "tiers.json"
    svc = TierService(FakeClient('{"tier": 5, "reason": "editor"}'), cache_path=cache)
    c = svc.classify("app-editors/vim-9.1")
    assert (c.tier, c.source) == (5, "llm")
    assert json.loads(cache.read_text())["app-editors/vim"]["tier"] == 5

    fake2 = FakeClient('{"tier": 5}')
    svc2 = TierService(fake2, cache_path=cache)
    c2 = svc2.classify("app-editors/vim")
    assert (c2.tier, c2.source) == (5, "cache")
    assert fake2.calls == 0


@pytest.mark.parametrize("client", [None, FakeClient(error=LLMError("down"))])
def test_model_down_is_conservative_and_uncached(tmp_path, client):
    cache = tmp_path / "tiers.json"
    svc = TierService(client, cache_path=cache)
    c = svc.classify("app-editors/emacs")
    assert (c.tier, c.source) == (1, "fallback")
    assert not cache.exists() or "app-editors/emacs" not in json.loads(cache.read_text())


def test_garbage_answer_is_fallback(tmp_path):
    svc = TierService(FakeClient("probably tier three?"), cache_path=tmp_path / "t.json")
    assert svc.classify("app-misc/odd").tier == 1


def test_system_set_hint_in_prompt(tmp_path):
    fake = FakeClient('{"tier": 2}')
    svc = TierService(fake, cache_path=tmp_path / "t.json")
    svc.classify("app-shells/zsh-5.9", in_system_set=True)
    assert fake.last_messages[-1]["content"].count("@system") == 1
    svc.classify("app-shells/fish", in_system_set=False)
    assert "@system" not in fake.last_messages[-1]["content"]


# ------------- consumer API on fake data (task 4.2) -------------


def _c(*tiers):
    return [Classification(f"cat/pkg{i}", t, "hint") for i, t in enumerate(tiers)]


def test_consumer_helpers():
    assert distribution(_c(5, 5, 1)) == {5: 2, 1: 1}
    assert most_critical(_c(5, 2, 4)) == 2
    assert snapshot_required(_c(5, 4)) is True
    assert snapshot_required(_c(5, 5)) is False


def test_noninteractive_autonomy_rule():
    assert noninteractive_auto_allowed(_c(5)[0]) is True
    assert noninteractive_auto_allowed(_c(1)[0]) is False
