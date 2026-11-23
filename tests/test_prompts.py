import io
import os

import pytest

from emerge_ai.config import Config
from emerge_ai import prompts
from emerge_ai.llm import LLMClient

ENDPOINT = os.environ.get("EMERGE_AI_TEST_ENDPOINT", "http://127.0.0.1:8080/v1")
MODEL = os.environ.get(
    "EMERGE_AI_TEST_MODEL", "qwen3.8-flash-next-unsloth-ud-q5_k_xl"
)


@pytest.fixture
def rules_dir(tmp_path, monkeypatch):
    d = tmp_path / "rules"
    (d / "rules").mkdir(parents=True)
    inner = d / "rules"
    (inner / "00-canary.md").write_text(
        "House rule: in this build the cat's name is Барсик. Never invent it."
    )
    (inner / "10-safety.md").write_text("Safety text.")
    monkeypatch.setenv(prompts.ENV_RULES_DIR, str(inner))
    return inner


def test_rules_loaded_sorted(rules_dir):
    rules = prompts.load_rules()
    assert rules.index("Барсик") < rules.index("Safety text")
    assert "## 00-canary" in rules


def _mk_rules(root, text):
    root.mkdir(parents=True, exist_ok=True)
    (root / "00-x.md").write_text(text)
    return root


def _no_env(monkeypatch):
    monkeypatch.delenv(prompts.ENV_RULES_DIR, raising=False)


def test_rules_dir_env_overrides_everything(tmp_path, monkeypatch):
    env_dir = _mk_rules(tmp_path / "env", "env rule")
    dev = _mk_rules(tmp_path / "dev", "dev rule")
    inst = _mk_rules(tmp_path / "inst", "inst rule")
    monkeypatch.setenv(prompts.ENV_RULES_DIR, str(env_dir))
    monkeypatch.setattr(prompts, "FALLBACK_RULES_DIR", str(dev))
    monkeypatch.setattr(prompts, "INSTALL_RULES_DIR", str(inst))
    assert prompts.rules_dir() == env_dir
    assert "env rule" in prompts.load_rules()


def test_rules_dir_prefers_dev_checkout(tmp_path, monkeypatch):
    dev = _mk_rules(tmp_path / "dev", "dev rule")
    inst = _mk_rules(tmp_path / "inst", "inst rule")
    _no_env(monkeypatch)
    monkeypatch.setattr(prompts, "FALLBACK_RULES_DIR", str(dev))
    monkeypatch.setattr(prompts, "INSTALL_RULES_DIR", str(inst))
    assert prompts.rules_dir() == dev
    assert "dev rule" in prompts.load_rules()


def test_rules_dir_falls_back_to_install_dir(tmp_path, monkeypatch):
    inst = _mk_rules(tmp_path / "inst", "inst rule")
    _no_env(monkeypatch)
    monkeypatch.setattr(prompts, "FALLBACK_RULES_DIR", str(tmp_path / "missing-dev"))
    monkeypatch.setattr(prompts, "INSTALL_RULES_DIR", str(inst))
    assert prompts.rules_dir() == inst
    assert "inst rule" in prompts.load_rules()


def test_rules_dir_env_set_even_if_missing(tmp_path, monkeypatch):
    dev = _mk_rules(tmp_path / "dev", "dev rule")
    missing = tmp_path / "missing-env"
    monkeypatch.setenv(prompts.ENV_RULES_DIR, str(missing))
    monkeypatch.setattr(prompts, "FALLBACK_RULES_DIR", str(dev))
    assert prompts.rules_dir() == missing
    with pytest.raises(FileNotFoundError, match="no prompt rules found") as exc:
        prompts.load_rules()
    assert str(missing) in str(exc.value)
    assert str(dev) not in str(exc.value)


def test_rules_error_lists_all_checked_dirs(tmp_path, monkeypatch):
    missing_dev = tmp_path / "missing-dev"
    missing_inst = tmp_path / "missing-inst"
    _no_env(monkeypatch)
    monkeypatch.setattr(prompts, "FALLBACK_RULES_DIR", str(missing_dev))
    monkeypatch.setattr(prompts, "INSTALL_RULES_DIR", str(missing_inst))
    with pytest.raises(FileNotFoundError) as exc:
        prompts.load_rules()
    assert str(missing_dev) in str(exc.value)
    assert str(missing_inst) in str(exc.value)


def test_context_extracts_profile_and_use():
    info = (
        "Portage 3.0.82\nProfile: default/linux/amd64/23.0\n"
        "USE: multilib systemd -gtk\n"
    )
    ctx = prompts.collect_context(info, language="russian")
    assert ctx["profile"] == "default/linux/amd64/23.0"
    assert "systemd" in ctx["use_flags"]
    assert ctx["language"] == "russian"


def test_assemble_contains_rules_context_language(rules_dir):
    rules = prompts.load_rules()
    ctx = prompts.collect_context("Portage 3.0.82", "russian")
    sp = prompts.assemble_system_prompt(rules, ctx)
    assert "Барсик" in sp
    assert "init:" in sp and "root filesystem:" in sp
    assert "respond in russian" in sp


def test_write_generated(tmp_path):
    rules = "R"
    path = prompts.write_generated("SP", directory=tmp_path / "gen")
    assert "SP" in path.read_text()


@pytest.mark.integration
def test_live_system_rules_reach_model(rules_dir):
    rules = prompts.load_rules()
    ctx = prompts.collect_context("Portage 3.0.82", "english")
    sp = prompts.assemble_system_prompt(rules, ctx)
    client = LLMClient(Config(endpoint=ENDPOINT, model=MODEL))
    resp = client.chat(
        [
            {"role": "system", "content": sp},
            {"role": "user", "content": "What is the cat's name in this build?"},
        ]
    )
    assert "Барсик" in resp.content
