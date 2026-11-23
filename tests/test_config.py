import pytest

from emerge_ai.config import Config, ConfigError, load_config, require_endpoint


def test_defaults():
    cfg = Config()
    assert not hasattr(cfg, "reasoning_show")
    assert cfg.language == "auto"
    assert cfg.web_access is True


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
        ("auto", "ru_RU.UTF-8", "russian"),
        ("auto", "en_US.UTF-8", "english"),
        ("auto", "", "english"),
        ("deutsch", "ru_RU.UTF-8", "deutsch"),
    ],
)
def test_resolved_language(monkeypatch, language, lang_env, expected):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", lang_env)
    assert Config(language=language).resolved_language() == expected
