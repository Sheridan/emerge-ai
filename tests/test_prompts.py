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
