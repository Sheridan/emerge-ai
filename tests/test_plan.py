from emerge_ai.plan import Plan, PlanEntry, build_plan
from emerge_ai.tiers import TierService


class FakePackage:
    """Portage-shaped (fix-queued-plan-parsing D2): a --pretend altlist yields
    Package-like entries with cpv/installed — no .pkg anywhere."""

    def __init__(self, cpv, installed=False):
        self.cpv = cpv
        self.installed = installed


class FakeGraph:
    def altlist(self):
        return [
            FakePackage("sys-libs/glibc-2.42"),
            FakePackage("app-editors/vim-9.1"),
            FakePackage("sys-libs/ncurses-6.5", installed=True),  # not scheduled
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


class FakeParseOpts:
    """_emerge.main.parse_opts-shaped: (action, opts, files) from argv."""

    def __call__(self, argv):
        opts = {"--update": True, "--deep": True, "--newuse": True, "--ask": True}
        return None, dict(opts), [a for a in argv if not a.startswith("-")]


def test_plan_fixture_distribution(tmp_path):
    resolve = FakeResolve()
    svc = TierService(client=None, cache_path=tmp_path / "t.json")  # glibc hint, vim fallback
    plan = build_plan(
        ["sys-apps/foo"],
        svc,
        parse_opts=FakeParseOpts(),
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
        parse_opts=FakeParseOpts(),
        load_config=FakeConfigLoader(),
        resolve=FakeResolve(),
        system_atoms={"app-editors/vim"},
    )
    assert len(plan.entries) == 2
    assert len(client.user_prompts) == 1  # glibc resolved from hints, no LLM
    assert "app-editors/vim" in client.user_prompts[0]
    assert "@system" in client.user_prompts[0]


PRETEND = """These are the packages that would be merged, in order:

Calculating dependencies... done!
\x1b[32;01m[ebuild   R    ]\x1b[0m sys-libs/glibc-2.42::gentoo  USE="nls" 0 KiB
[ebuild   U    ] [app-editors/vim-9.1:0::gentoo] USE="X" 1 KiB
[blocks B      ] <app-editors/vim-9.1:0 ("...is blocking...")
\x1b[32;01m[ebuild   R    ]\x1b[0m sys-libs/glibc-2.42::gentoo  (duplicate line) 0 KiB

Total: 2 packages, in 1 segment
"""


def _svc(tmp_path):
    return TierService(client=None, cache_path=tmp_path / "t.json")


def test_build_plan_from_output_matches_resolver(tmp_path):
    from emerge_ai.plan import build_plan_from_output

    resolver_plan = build_plan(["x"], _svc(tmp_path), parse_opts=FakeParseOpts(),
                               load_config=FakeConfigLoader(), resolve=FakeResolve())
    parsed = build_plan_from_output(PRETEND, ["x"], _svc(tmp_path),
                                    fallback=lambda a, s: None)
    assert [(e.cpv, e.tier) for e in parsed.entries] == [
        (e.cpv, e.tier) for e in resolver_plan.entries
    ]  # glibc first (merge order preserved), repo/slot/brackets/ANSI stripped


def test_build_plan_from_output_dedups_keeps_first(tmp_path):
    from emerge_ai.plan import build_plan_from_output

    out = PRETEND + "[ebuild   R    ] sys-libs/glibc-2.42::gentoo  again\n"
    plan = build_plan_from_output(out, ["x"], _svc(tmp_path), fallback=lambda a, s: None)
    assert [e.cpv for e in plan.entries] == ["sys-libs/glibc-2.42", "app-editors/vim-9.1"]


def test_build_plan_from_output_falls_back_on_unparseable(tmp_path):
    from emerge_ai.plan import build_plan_from_output

    calls = []

    def fallback(args, svc):
        calls.append((args, svc))
        return "sentinel"

    for junk in ("app-misc/foo-1.0\n", "", "Total: 0 packages\n", "[ebuild ] malformed\n"):
        svc = _svc(tmp_path)
        assert build_plan_from_output(junk, ["-q", "x"], svc, fallback=fallback) == "sentinel"
    assert [c[0] for c in calls] == [["-q", "x"]] * 4  # args passed through untouched


def test_build_plan_honest_seam_resolves_user_argv_without_nodeps(tmp_path):
    """spec: run-reporting (queue requirement) — the fallback resolves the
    user's own argv the way emerge does: no --nodeps (that altlist is the
    whole set closure), --pretend forced, --ask dropped, queue = altlist
    minus installed."""
    resolve = FakeResolve()
    plan = build_plan(["-uDN", "--ask", "@world"], _svc(tmp_path),
                      parse_opts=FakeParseOpts(), load_config=FakeConfigLoader(),
                      resolve=resolve)
    opts = resolve.cfg_args["opts"]
    assert "--nodeps" not in opts
    assert opts["--pretend"] is True and opts["--quiet"] is True
    assert opts["--update"] is True  # the user's own flags reach the resolver
    assert "--ask" not in opts
    assert [e.cpv for e in plan.entries] == ["sys-libs/glibc-2.42", "app-editors/vim-9.1"]


# live-host shapes (fix-queued-plan-parsing): masked/keyworded status flags in
# the bracket, old-version and USE payloads after the cpv, blocks line beside
PRETEND_MASKED = """These are the packages that would be merged, in order:

[ebuild     U ~] dev-libs/jemalloc-5.4.0-r2::gentoo [5.3.0::gentoo] USE="stats" 0 KiB
\x1b[32;01m[ebuild  N    *]\x1b[0m app-misc/yazi-26.9.1::gentoo  USE="lua" 2 KiB
[ebuild     R ~] app-editors/neovim-0.11.2::gentoo [0.11.1::gentoo] 0 KiB
[blocks B      ] <app-misc/yazi-data-25 ("<app-misc/yazi-data-25 is blocking...")

Total: 3 packages, in 1 segment
"""


def test_build_plan_from_output_counts_masked_status_flags(tmp_path):
    from emerge_ai.plan import build_plan_from_output

    plan = build_plan_from_output(PRETEND_MASKED, ["-uDN", "@world"], _svc(tmp_path),
                                  fallback=lambda a, s: None)
    assert [e.cpv for e in plan.entries] == [
        "dev-libs/jemalloc-5.4.0-r2", "app-misc/yazi-26.9.1", "app-editors/neovim-0.11.2",
    ]
