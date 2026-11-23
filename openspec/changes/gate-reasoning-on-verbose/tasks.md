# Tasks

## 1. LLMClient: show_reasoning вместо cfg.reasoning_show (llm.py, agent.py)

- [x] 1.1 `LLMClient.__init__(..., *, show_reasoning: bool = False)`; `render` печатает `[reasoning]` по `self.show_reasoning` (docstring обновить); в `tests/test_llm.py` `test_render_reasoning_only_when_enabled` перевести на `show_reasoning=True/False`; `pytest tests/test_llm.py -k render` — зелено
- [x] 1.2 `IncidentAgent.propose(..., render_to=None)` прокидывает в `run_tool_loop`; тест в `tests/test_agent.py`: со стабовым клиентом и `render_to=StringIO` rounds стримятся, без render_to — нет; `pytest tests/test_agent.py` — зелено
- [x] 1.3 `_live_client` в `tests/test_llm.py` (`test_live_reasoning_visibility`) перевести на `show_reasoning`; прогнать live-тест при доступном локальном эндпоинте (`pytest tests/test_llm.py -k live` — skip без эндпоинта допустим)

## 2. Конфиг: удаление reasoning_show (config.py)

- [x] 2.1 Убрать `reasoning_show` из `DEFAULTS` и `Config`; `_REMOVED_KEYS = {"reasoning_show": ...}` с адресным warning в `from_dict` (общий unknown-key для него не печатается); обновить `tests/test_config.py`: дефолт без ключа + тест «reasoning_show в конфиге → warning содержит -v/--verbose, запуск не упал»; `pytest tests/test_config.py` — зелено

## 3. CLI: verbose-детект и проброс (cli.py)

- [x] 3.1 `VERBOSE_FLAGS = ("-v", "--verbose")`; в `main()` `verbose = flag_present(emerge_args, VERBOSE_FLAGS)` рядом с pretend/ask; проброс `show_reasoning=verbose` в `_make_tier_service`, `_maybe_agent`, `_changelog_mode`, `_etc_flow` (`client_factory(cfg, show_reasoning=verbose)`); `pytest tests/test_cli.py tests/test_cli_integration.py` — зелено (существующие)
- [x] 3.2 CLI-тесты: (a) `cli.main(["-av", "x"])` → emerge-stub вызван с `["-av", ...]` (флаг не вырезан, кластер распознан); (b) `_maybe_agent` при verbose конструирует `LLMClient` с `show_reasoning=True` (monkeypatch перехват kwargs), без `-v` — False; `pytest tests/test_cli.py -k "verbose or reasoning"` — зелено

## 4. Документация

- [x] 4.1 README: убрать `reasoning_show` из примера конфига и списка опций; добавить в таблицу флагов/примечания: «`-v`/`--verbose` (эмерджа, passthrough) дополнительно включает вывод рассуждений модели; по умолчанию выключен»; проверить текст глазами против секции «Конфиг»

## 5. Интеграционная проверка

- [ ] 5.1 Полный `pytest` — зелено; `openspec validate gate-reasoning-on-verbose --strict` без ошибок; сценарии дельты config-prompts сверены с тестами (каждый сценарий → тест, соответствие в commit message)
- [ ] 5.2 Ручная smoke без live-мутаций: конфиг со `"reasoning_show": true` → warning про `-v/--verbose`; `emerge-ai -p ...` и `emerge-ai -pv ...` при наличии эндпоинта — reasoning виден только во втором

## Workflow follow-up

- Архивировать change после ревью (дельта синкается в `openspec/specs/config-prompts/spec.md`).
