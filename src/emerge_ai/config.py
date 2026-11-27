"""Config load & validation (spec: config-prompts)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from emerge_ai import ui

CONFIG_PATH = "/etc/portage/emerge-ai.json"

DEFAULTS = {
    "endpoint": None,
    "model": None,
    "api_key": None,
    "language": "auto",
    "web_access": True,
    "show_digest": True,
    "etc_update_after_build": True,
    # automatic changelog digest after a successful run; off by default:
    # sources touch the network (spec: run-reporting, unset => silent)
    "changelog_digest": False,
    "gh_repos": [],
    "git_urls": [],
    "news_dir": "/var/lib/eselect-news/news",
    "llm_colors": dict(ui.DEFAULT_LLM_COLORS),
}

# Old file-level key names -> canonical keys (spec: config-prompts). Aliases are
# readable with a deprecation warning; the canonical key wins on conflict.
_ALIASES = {
    "post_run_digest": "show_digest",
    "etc_update_llm": "etc_update_after_build",
}

# Keys accepted in old configs, now gone: key -> where it went.
_REMOVED_KEYS = {
    "reasoning_show": "was removed; reasoning output is now controlled by the emerge flag -v/--verbose",
}

# Language codes and common names -> full English name used in prompt
# directives (spec: config-prompts); unknown values pass through as written.
LANGUAGE_NAMES = {
    "ru": "Russian", "russian": "Russian",
    "en": "English", "english": "English",
    "uk": "Ukrainian", "ukrainian": "Ukrainian",
    "de": "German", "german": "German",
    "fr": "French", "french": "French",
    "es": "Spanish", "spanish": "Spanish",
}


def _lang_code(value: str) -> str:
    return value.strip().lower().replace("-", "_").split("_", 1)[0].split(".", 1)[0]


def normalize_language(value: str) -> str:
    """`ru`/`ru_RU.UTF-8`/`russian` -> `Russian`; unknown -> value as written."""
    raw = value.strip()
    return LANGUAGE_NAMES.get(_lang_code(raw), raw)


class ConfigError(Exception):
    pass


@dataclass
class Config:
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    language: str = "auto"
    web_access: bool = True
    show_digest: bool = True
    etc_update_after_build: bool = True
    changelog_digest: bool = False
    gh_repos: list = field(default_factory=list)
    git_urls: list = field(default_factory=list)
    news_dir: str = "/var/lib/eselect-news/news"
    llm_colors: dict = field(default_factory=lambda: dict(ui.DEFAULT_LLM_COLORS))
    source: str | None = field(default=None, compare=False)

    @classmethod
    def from_dict(cls, data: dict, source: str | None = None, warn=None) -> "Config":
        if warn is None:
            def warn(msg: str) -> None:
                print(msg, file=sys.stderr)
        data = dict(data)
        # canonical web_access lives under the nested "agent" section; the flat
        # key stays a readable alias, the dataclass attribute stays flat (D1)
        if "agent" in data:
            agent = data.pop("agent")
            if isinstance(agent, dict):
                for sub in sorted(set(agent) - {"web_access"}):
                    warn(f"emerge-ai: config: ignoring unknown key 'agent.{sub}'")
                if "web_access" in agent:
                    if "web_access" in data:
                        warn("emerge-ai: config: flat 'web_access' ignored: 'agent.web_access' wins")
                    data["web_access"] = agent["web_access"]
            else:
                warn("emerge-ai: config: 'agent' must be a JSON object; ignoring")
        elif "web_access" in data:
            warn("emerge-ai: config: key 'web_access' is deprecated, use 'agent.web_access'")
        for old, new in sorted(_ALIASES.items()):
            if old not in data:
                continue
            value = data.pop(old)
            if new in data:
                warn(f"emerge-ai: config: key {old!r} is deprecated and ignored, {new!r} is set")
            else:
                warn(f"emerge-ai: config: key {old!r} is deprecated, use {new!r}")
                data[new] = value
        unknown = set(data) - set(DEFAULTS) - set(_REMOVED_KEYS) - set(_ALIASES)
        for key in sorted(unknown):
            warn(f"emerge-ai: config: ignoring unknown key {key!r}")
        for key in sorted(_REMOVED_KEYS):
            if key in data:
                warn(f"emerge-ai: config: key {key!r} {_REMOVED_KEYS[key]}")
        kwargs = {k: data[k] for k in DEFAULTS if k in data}
        if "llm_colors" in kwargs:
            kwargs["llm_colors"] = ui.resolve_palette(kwargs["llm_colors"], warn=warn)
        return cls(source=source, **kwargs)

    def resolved_language(self) -> str:
        # single normalization point for every language-aware prompt (spec:
        # config-prompts); call-sites must never pass raw cfg.language
        if self.language != "auto":
            return normalize_language(self.language)
        env_lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        code = _lang_code(env_lang)
        return LANGUAGE_NAMES.get(code, "English")


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
