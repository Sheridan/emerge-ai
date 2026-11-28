import json

import pytest

from aimerge.config import Config, ConfigError, load_config, require_endpoint


def test_defaults():
    cfg = Config()
    assert not hasattr(cfg, "reasoning_show")
    assert cfg.language == "auto"
    assert cfg.web_access is True
    assert cfg.show_digest is True and cfg.etc_update_after_build is True
    assert cfg.changelog_digest is False  # auto digest is opt-in (run-reporting)


def test_canonical_keys_apply_without_warnings(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "show_digest": False, "etc_update_after_build": False,
        "changelog_digest": False, "agent": {"web_access": False},
    }))
    p.chmod(0o600)  # avoid the loose-mode warning, err must be pristine
    cfg = load_config(p)
    assert cfg.show_digest is False and cfg.etc_update_after_build is False
    assert cfg.changelog_digest is False and cfg.web_access is False
    err = capsys.readouterr().err
    assert err == ""  # spec-shaped config: no deprecation, no unknown-key noise


@pytest.mark.parametrize("old,new", [
    ("post_run_digest", "show_digest"),
    ("etc_update_llm", "etc_update_after_build"),
])
def test_legacy_aliases_warn_and_map(tmp_path, capsys, old, new):
    p = tmp_path / "cfg.json"
    p.write_text(f'{{"{old}": false}}')
    cfg = load_config(p)
    assert getattr(cfg, new) is False
    err = capsys.readouterr().err
    assert "deprecated" in err and new in err


def test_flat_web_access_alias(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"web_access": false}')
    cfg = load_config(p)
    assert cfg.web_access is False
    err = capsys.readouterr().err
    assert "deprecated" in err and "agent.web_access" in err


def test_canonical_wins_over_alias(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"etc_update_after_build": false, "etc_update_llm": true}')
    cfg = load_config(p)
    assert cfg.etc_update_after_build is False
    err = capsys.readouterr().err
    assert "ignored" in err and "etc_update_llm" in err


def test_agent_section_must_be_object(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"agent": 5}')
    cfg = load_config(p)
    assert cfg.web_access is True  # defaults kept
    err = capsys.readouterr().err
    assert "must be a JSON object" in err


def test_removed_reasoning_show_key_warns_with_pointer(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"endpoint": "http://x/v1", "reasoning_show": true}')
    cfg = load_config(p)
    assert cfg.endpoint == "http://x/v1"  # startup did not break
    err = capsys.readouterr().err
    assert "reasoning_show" in err and "-v/--verbose" in err
    assert "unknown key" not in err  # targeted warning instead of the generic one


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "absent.json")
    assert cfg.endpoint is None
    with pytest.raises(ConfigError, match="endpoint"):
        require_endpoint(cfg)


def test_0600_ok_and_loose_mode_warns(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"endpoint": "http://x/v1"}')
    p.chmod(0o600)
    assert load_config(p).endpoint == "http://x/v1"
    assert "warning" not in capsys.readouterr().err

    p.chmod(0o644)
    cfg = load_config(p)
    assert cfg.endpoint == "http://x/v1"
    assert "600" in capsys.readouterr().err


def test_unknown_key_ignored_with_warning(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"endpoint": "http://x/v1", "wat": 1}')
    cfg = load_config(p)
    assert cfg.endpoint == "http://x/v1"
    assert "wat" in capsys.readouterr().err


def test_llm_colors_absent_gives_defaults(tmp_path, capsys):
    cfg = load_config(tmp_path / "absent.json")
    assert cfg.llm_colors == {"content": "cyan", "reasoning": "dim", "question": "yellow"}
    assert capsys.readouterr().err == ""


def test_llm_colors_partial_dict(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"llm_colors": {"content": "magenta", "question": "off"}}')
    cfg = load_config(p)
    assert cfg.llm_colors == {"content": "magenta", "reasoning": "dim", "question": "off"}


def test_llm_colors_invalid_name_warns_and_defaults_field(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"llm_colors": {"content": "hot-pink", "reasoning": "bold"}}')
    cfg = load_config(p)
    assert cfg.llm_colors["content"] == "cyan"
    assert cfg.llm_colors["reasoning"] == "bold"
    err = capsys.readouterr().err
    assert "llm_colors.content" in err and "hot-pink" in err


def test_llm_colors_non_dict_warns_all_defaults(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"llm_colors": "cyan"}')
    cfg = load_config(p)
    assert cfg.llm_colors == {"content": "cyan", "reasoning": "dim", "question": "yellow"}
    assert "JSON object" in capsys.readouterr().err


def test_llm_colors_key_not_reported_unknown(tmp_path, capsys):
    p = tmp_path / "cfg.json"
    p.write_text('{"llm_colors": {"content": "red"}}')
    assert load_config(p).llm_colors["content"] == "red"
    assert "unknown key" not in capsys.readouterr().err


def test_broken_json_raises(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{not json")
    with pytest.raises(ConfigError, match="cannot parse"):
        load_config(p)


@pytest.mark.parametrize(
    ("language", "lang_env", "expected"),
    [
        ("auto", "ru_RU.UTF-8", "Russian"),
        ("auto", "en_US.UTF-8", "English"),
        ("auto", "", "English"),
        ("auto", "C", "English"),
        ("auto", "de_DE.UTF-8", "German"),
        ("auto", "uk", "Ukrainian"),
        ("deutsch", "ru_RU.UTF-8", "deutsch"),  # unknown — as written
        ("ru", "", "Russian"),                  # short code normalizes
        ("ru_RU.UTF-8", "", "Russian"),         # region/encoding sliced off
        ("russian", "", "Russian"),             # full name stays a full name
        ("en", "", "English"),
        ("xx", "", "xx"),
    ],
)
def test_resolved_language(monkeypatch, language, lang_env, expected):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", lang_env)
    assert Config(language=language).resolved_language() == expected


def test_resolved_language_lc_all_wins(monkeypatch):
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    assert Config(language="auto").resolved_language() == "Russian"
