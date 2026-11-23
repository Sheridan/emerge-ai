import subprocess
from pathlib import Path

import pytest

from emerge_ai import changelog


def make_git_repo(tmp_path):
    repo = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(repo), str(work)], check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    for i, msg in enumerate(["fix: security patch X", "docs: typo", "feat: breaking config format"]):
        (work / f"f{i}").write_text("x")
        subprocess.run(["git", "-C", str(work), "add", "."], check=True)
        subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", msg], check=True, env=env)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "HEAD"], check=True)
    return str(repo)


def test_github_releases_mocked():
    data = [{"tag_name": "v1.2", "body": "fix CVE-2026-0001"}, {"tag_name": "v1.1", "body": "trivia"}]
    releases = changelog.github_releases("foo/bar", fetch_json=lambda url: data)
    assert releases[0]["title"] == "v1.2" and "CVE" in releases[0]["text"]
    assert releases[0]["source"] == "github:foo/bar"


def test_git_commits_fixture(tmp_path):
    url = make_git_repo(tmp_path)
    got = changelog.git_commits(url, str(tmp_path / "cache"))
    subjects = [g["title"] for g in got]
    assert "fix: security patch X" in subjects
    assert all("error" not in g for g in got)


def test_unavailable_source_reported_not_fatal(tmp_path):
    def boom(url):
        raise OSError("network down")
    text = changelog.collect_digest(
        gh_repos=["ghost/repo"], git_urls=["/nonexistent/repo.git"],
        news_dir=str(tmp_path / "none"), fetch_json=boom,
    )
    assert "unavailable: github:ghost/repo" in text
    assert "git clone unavailable" in text or "unavailable" in text


def test_llm_digest_marks_unavailable():
    class Fake:
        def chat(self, messages, tools=None, temperature=0.2):
            self.messages = messages
            return type("R", (), {"content": "- security patch X (git:upstream.git)"})()
    items = [{"source": "git:upstream.git", "title": "fix: security patch X", "text": "x"}]
    out = changelog.llm_digest(Fake(), items, ["github:foo/bar (OSError)"])
    assert "security patch X" in out
    f = Fake()
    changelog.llm_digest(f, items, ["github:foo/bar (OSError)"])
    assert "Unavailable sources" in f.messages[1]["content"]


def test_use_diff():
    d = changelog.use_diff({"a/b-1": {"x", "y"}}, {"a/b-1": {"y", "z"}})
    assert d == ["a/b-1: +USE z", "a/b-1: -USE x"]
