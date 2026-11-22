from types import SimpleNamespace

from emerge_ai.plan import Plan, PlanEntry, build_plan
from emerge_ai.tiers import TierService


class FakeGraph:
    def altlist(self):
        return [
            SimpleNamespace(pkg="sys-libs/glibc-2.42"),
            SimpleNamespace(pkg="app-editors/vim-9.1"),
        ]


class FakeResolve:
    def __init__(self):
        self.cfg_args = None

    def __call__(self, cfg, spinner=None):
        self.cfg_args = cfg
        return True, FakeGraph(), []


class FakeConfigLoader:
    def __call__(self, action, args, opts):
        return {"action": action, "args": args, "opts": opts}


def test_plan_fixture_distribution(tmp_path):
    resolve = FakeResolve()
    svc = TierService(client=None, cache_path=tmp_path / "t.json")  # glibc hint, vim fallback
    plan = build_plan(
        ["sys-apps/foo"],
        svc,
        load_config=FakeConfigLoader(),
        resolve=resolve,
    )
    dist = plan.distribution
    glibc = next(e for e in plan.entries if e.cpv.startswith("sys-libs/glibc"))
    assert glibc.tier == 1 and glibc.tier_source == "hint"
    vim = next(e for e in plan.entries if e.cpv.startswith("app-editors/vim"))
    assert vim.tier == 1 and vim.tier_source == "fallback"
    assert dist[1] == 2


def test_plan_system_membership(tmp_path):
    from emerge_ai.llm import Response

    class CapturingClient:
        def __init__(self):
            self.user_prompts = []

        def chat(self, messages, tools=None, temperature=0.2):
            self.user_prompts.append(messages[-1]["content"])
            return Response(content='{"tier": 5, "reason": "ok"}')

    client = CapturingClient()
    svc = TierService(client, cache_path=tmp_path / "t.json")
    plan = build_plan(
        ["x"],
        svc,
        load_config=FakeConfigLoader(),
        resolve=FakeResolve(),
        system_atoms={"app-editors/vim"},
    )
    assert len(plan.entries) == 2
    assert len(client.user_prompts) == 1  # glibc resolved from hints, no LLM
    assert "app-editors/vim" in client.user_prompts[0]
    assert "@system" in client.user_prompts[0]
