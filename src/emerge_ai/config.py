"""Config load & validation (spec: config-prompts)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = "/etc/portage/emerge-ai.json"

DEFAULTS = {
    "endpoint": None,
    "model": None,
    "api_key": None,
    "reasoning_show": True,
    "language": "auto",
    "web_access": True,
    "etc_update_llm": True,
    "post_run_digest": True,
    "gh_repos": [],
    "git_urls": [],
    "news_dir": "/var/lib/eselect-news/news",
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    reasoning_show: bool = True
    language: str = "auto"
    web_access: bool = True
    etc_update_llm: bool = True
    post_run_digest: bool = True
    gh_repos: list = field(default_factory=list)
    git_urls: list = field(default_factory=list)
    news_dir: str = "/var/lib/eselect-news/news"
    source: str | None = field(default=None, compare=False)

    @classmethod
    def from_dict(cls, data: dict, source: str | None = None, warn=None) -> "Config":
        if warn is None:
            def warn(msg: str) -> None:
                print(msg, file=sys.stderr)
        unknown = set(data) - set(DEFAULTS)
        for key in sorted(unknown):
            warn(f"emerge-ai: config: ignoring unknown key {key!r}")
        kwargs = {k: data[k] for k in DEFAULTS if k in data}
        return cls(source=source, **kwargs)

    def resolved_language(self) -> str:
        if self.language != "auto":
            return self.language
        env_lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        if env_lang.lower().startswith("ru"):
            return "russian"
        return "english"


def config_path(path: str | Path | None = None) -> Path:
    override = os.environ.get("EMERGE_AI_CONFIG")
    if override and path in (None, CONFIG_PATH):
        return Path(override)
    return Path(CONFIG_PATH if path is None else path)


def load_config(path: str | Path = CONFIG_PATH, warn=None) -> Config:
    if warn is None:
        def warn(msg: str) -> None:
            print(msg, file=sys.stderr)
    path = config_path(path)
    if not path.exists():
        cfg = Config()
        cfg.source = str(path)
        return cfg
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        warn(
            f"emerge-ai: warning: {path} is mode {mode:04o}; it may hold an API key, "
            "chmod 600 recommended"
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"emerge-ai: cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"emerge-ai: {path} must contain a JSON object")
    return Config.from_dict(data, source=str(path), warn=warn)


def require_endpoint(cfg: Config) -> str:
    if not cfg.endpoint:
        raise ConfigError(
            f"emerge-ai: no LLM endpoint configured; set \"endpoint\" in {cfg.source or CONFIG_PATH}"
        )
    return cfg.endpoint
