"""Changelog digest (spec: digest-changelog): local sources (eselect news,
GLESA advisory list, USE diffs) plus external sources (GitHub releases API,
shallow git clones into a cache), reduced to "the most important" by the LLM.
An unavailable source never kills the digest — it is reported as unavailable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from emerge_ai import injection
from emerge_ai.prompts import PLAIN_TEXT_DIRECTIVE

NEWS_DIR = "/var/lib/eselect-news/news"
GLESA_INDEX = "/var/cache/portage/glsa/index-cache"  # may be absent -> unavailable


def read_news(news_dir: str = NEWS_DIR, limit: int = 5) -> list[dict]:
    d = Path(news_dir)
    if not d.is_dir():
        return []
    files = sorted((f for f in d.glob("*.news") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        text = f.read_text(errors="replace")
        title = next((l for l in text.splitlines() if l.startswith("Title:")), f.name)
        out.append({"source": str(f), "title": title.removeprefix("Title:").strip(), "text": text[:2000]})
    return out


def read_glesa(path: str = GLESA_INDEX, limit: int = 10) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return sorted((f.name for f in p.rglob("*.xml")), reverse=True)[:limit]


def use_diff(old_use: dict, new_use: dict) -> list[str]:
    lines = []
    for cpv in sorted(set(old_use) | set(new_use)):
        a, b = set(old_use.get(cpv, [])), set(new_use.get(cpv, []))
        for flag in sorted(b - a):
            lines.append(f"{cpv}: +USE {flag}")
        for flag in sorted(a - b):
            lines.append(f"{cpv}: -USE {flag}")
    return lines


def github_releases(repo: str, fetch_json=None, token: str | None = None) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    if fetch_json is None:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "emerge-ai"} | ({"Authorization": f"Bearer {token}"} if token else {}))
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    else:
        data = fetch_json(url)
    return [
        {"source": f"github:{repo}", "title": r.get("tag_name", "?"), "text": (r.get("body") or "")[:2000]}
        for r in data[:5]
    ]


def _run_git_log(dest: Path, depth: int) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(dest), "log", "--no-merges", f"--max-count={depth}", "--pretty=%s"],
        capture_output=True, text=True, timeout=60,
    )
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def git_commits(url: str, cache_dir: str, depth: int = 20) -> list[dict]:
    dest = Path(cache_dir) / url.rstrip("/").split("/")[-1].removesuffix(".git")
    if (dest / ".git").is_dir():
        subprocess.run(["git", "-C", str(dest), "fetch", "--depth", str(depth), "--quiet", "origin"],
                       capture_output=True, timeout=120)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["git", "clone", "--depth", str(depth), "--quiet", url, str(dest)],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return [{"error": f"git clone unavailable: {proc.stderr.strip()[-200:]}"}]
    return [{"source": f"git:{dest.name}", "title": line, "text": line} for line in _run_git_log(dest, depth)]


CHANGE_SYSTEM = (
    "You are the changelog digest of emerge-ai. From the collected change sources pick "
    "what a Gentoo sysadmin MUST know before the next world update: security fixes, "
    "breaking config changes, USE/profile changes, news requiring action. Output a short "
    "bulleted list, each bullet citing its source id; skip trivia. If everything is trivia "
    "say: nothing important. "
    + PLAIN_TEXT_DIRECTIVE
)


def llm_digest(client, items: list[dict], unavailable: list[str], packages: list[str] = ()) -> str:
    corpus = "\n\n".join(
        injection.wrap_untrusted(f"{i['source']} :: {i['title']}\n{i['text']}", source=i["source"])
        for i in items
    )
    tail = ("\n\nUnavailable sources: " + ", ".join(unavailable)) if unavailable else ""
    if packages:
        # focus the selection on what this run actually built (CPVs are foreign)
        tail += "\n\n" + injection.wrap_untrusted(
            "Merged in this run: " + ", ".join(packages), source="run-plan"
        )
    resp = client.chat(
        [{"role": "system", "content": CHANGE_SYSTEM},
         {"role": "user", "content": (corpus or "(no items)") + tail}]
    )
    return getattr(resp, "content", resp) or "empty reply"


def collect_digest(
    *,
    gh_repos: list[str] = (),
    git_urls: list[str] = (),
    git_cache: str = "/var/cache/emerge-ai/git",
    news_dir: str = NEWS_DIR,
    glsa_index: str = GLESA_INDEX,
    fetch_json=None,
    client=None,
    packages: list[str] = (),
) -> str:
    items, unavailable = [], []
    try:
        items += read_news(news_dir)
    except OSError as exc:
        unavailable.append(f"news: {exc}")
    try:
        items += [{"source": "glsa", "title": g, "text": g} for g in read_glesa(glsa_index)]
    except OSError as exc:
        unavailable.append(f"glsa: {exc}")
    for repo in gh_repos:
        try:
            items += github_releases(repo, fetch_json=fetch_json)
        except Exception as exc:
            unavailable.append(f"github:{repo} ({type(exc).__name__})")
    for url in git_urls:
        try:
            got = git_commits(url, git_cache)
        except Exception as exc:
            unavailable.append(f"git:{url} ({type(exc).__name__})")
            continue
        for g in got:
            if "error" in g:
                unavailable.append(g["error"])
            else:
                items.append(g)
    if client is None:
        lines = [f"- {i['source']}: {i['title']}" for i in items]
        for u in unavailable:
            lines.append(f"- unavailable: {u}")
        return "emerge-ai changelog digest (raw):\n" + "\n".join(lines or ["- no changes found"])
    return "emerge-ai changelog digest:\n" + llm_digest(client, items, unavailable, packages)
