"""News digest (spec: repair-actions, design D5) — aimerge reads the news
itself; the operator never gets a manual-reading pointer."""

import pytest

from aimerge import news

LISTING = (
    " [1: 1 of 3 ] GLSA 202611-01 [2026-11-20] (unread)\n"
    " [2: 2 of 3 ] Gentoo developer news [2026-11-02] (read)\n"
    " [3: 3 of 3 ] GLSA 202610-15 [2026-10-30] (unread)\n"
)


def fake_eselect(captured, list_out=LISTING, rc=0, binary_exists=True):
    def runner(argv, **kwargs):
        captured.append((list(argv), kwargs))
        if not binary_exists:
            raise OSError("No such file or directory: 'eselect'")

        class P:
            returncode, stderr = rc, ""
            stdout = list_out if argv[2:3] == ["list"] else "BODY of news\n"

        return P
    return runner


def test_list_unread_parses_eselect_output_and_skips_read():
    captured = []
    items = news.list_unread(runner=fake_eselect(captured))
    assert [i["id"] for i in items] == [1, 3]
    assert items[0]["title"] == "GLSA 202611-01" and items[0]["date"] == "2026-11-20"
    assert captured[0][0] == ["eselect", "news", "list"]


def test_list_unread_missing_eselect_is_not_an_error():
    assert news.list_unread(runner=fake_eselect([], binary_exists=False)) == []


def test_read_body_pins_pager_cat():
    captured = []
    body = news.read_body(3, runner=fake_eselect(captured))
    assert "BODY" in body
    argv, kwargs = captured[0]
    assert argv == ["eselect", "news", "read", "3"]
    assert kwargs["env"]["PAGER"] == "cat"


def test_report_without_endpoint_is_deterministic_title_date():
    captured = []
    lines = news.report_lines(news.list_unread(runner=fake_eselect(captured)),
                              runner=fake_eselect(captured))
    text = "\n".join(lines)
    assert "news digest: 2 unread item(s)" in text
    assert "[1] 2026-11-20 GLSA 202611-01" in text  # title + id + date
    assert "eselect news read" not in text and "manually" not in text
    assert "news list" not in text  # reading already happened here


def test_report_uses_llm_digest_and_wraps_untrusted():
    captured = []
    calls = []

    def summarize(messages):
        calls.append(messages)
        return {"choices": [{"message": {"content": "item 1: OpenSSL fix, high urgency"}}]}

    items = news.list_unread(runner=fake_eselect(captured))
    lines = news.report_lines(items, summarize=summarize,
                              plan_atoms=["dev-libs/openssl"],
                              runner=fake_eselect(captured))
    assert any("OpenSSL fix" in ln for ln in lines)
    user = calls[0][1]["content"]
    assert "<<<UNTRUSTED" in user and "news" in user  # injection envelope
    assert "dev-libs/openssl" in user
    system = calls[0][0]["content"]
    assert "never propose commands" in system and "UNTRUSTED DATA" in system


def test_report_llm_failure_falls_back_to_deterministic():
    captured = []

    def boom(messages):
        raise RuntimeError("endpoint down")

    items = news.list_unread(runner=fake_eselect(captured))
    lines = news.report_lines(items, summarize=boom, runner=fake_eselect(captured))
    assert "[1] 2026-11-20 GLSA 202611-01" in "\n".join(lines)


def test_backlog_guard_counts_the_rest():
    captured = []
    many = "".join(f" [{i}: {i} of 12 ] GLSA 2026{i:04d} [2026-01-{i:02d}] (unread)\n"
                   for i in range(1, 13))
    items = news.list_unread(runner=fake_eselect(captured, list_out=many))
    lines = news.report_lines(items, runner=fake_eselect(captured, list_out=many))
    body_reads = [c for c in captured if c[0][2:3] == ["read"]]
    assert len(body_reads) == news.MAX_BODIES  # bounded, not 12
    assert "2 more unread item(s)" in "\n".join(lines)
