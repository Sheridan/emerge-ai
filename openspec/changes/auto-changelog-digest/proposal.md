# Proposal

## Why

Спек run-reporting требует changelog-дайджест «при включённой опции» — то есть штатное, управляемое конфигом поведение по собраным пакетам (`openspec/specs/run-reporting/spec.md:37-46`). Реализованы только источники и LLM-отбор (`src/emerge_ai/changelog.py:19-151`), а вызов доступен исключительно как ручная команда `--changelog` (`src/emerge_ai/cli.py:296-297, 238-250`); `_post_run_digest` (`cli.py:229-236`) changelog не дёргает, опции `changelog_digest` в `DEFAULTS` нет (`src/emerge_ai/config.py:15-27`), в отчёт прогона (`state.RunState`, `src/emerge_ai/state.py:41-51`) дайджест не сохраняется (REVIEW_NOTES M11, `REVIEW_NOTES.md:165-169`). Решение — привести код к спеку: автоматический вызов после успешного прогона под новой опцией, ручной флаг сохраняется.

## What Changes

- Новая опция конфига `changelog_digest` (bool, **по умолчанию false**): включает автоматический changelog-дайджест после успешного прогона с собранными пакетами. Название — как в спековом словаре ключей (M10); сведение схем конфига — отдельное изменение `align-config-schema`, здесь только ключ.
- `_post_run_digest` после существующего post-run дайджеста строит changelog-дайджест через `changelog.collect_digest` (паттерн клиента при endpoint — как в `_changelog_mode`) и печатает его; отказ источников/LLM не влияет на код возврата прогона.
- Дайджест сохраняется в отчёт прогона: у `RunState` появляется поле `changelog`, записываемое существующим `state.save_run`; старые JSON-отчёты читаются по умолчанию `None`.
- Ручная команда `--changelog` и её вывод не меняются; `collect_digest` получает необязательный контекст «что собрано в этом прогоне» для фокуса LLM-отбора.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `run-reporting`: «Changelog-дайджест собранных пакетов» — печать plain text + сохранение в отчёт прогона, ручной `--changelog` остаётся; новое требование «Автоматический changelog-дайджест после прогона» — триггер, опция, деградация без endpoint, тишина по умолчанию.

## Impact

- `src/emerge_ai/config.py`: `DEFAULTS["changelog_digest"] = False` + поле `Config` (рядом с `post_run_digest`, `config.py:15-27, 48-49`).
- `src/emerge_ai/cli.py`: `_post_run_digest` (`cli.py:229-236`) — шаг changelog после general-дайджеста; вызовы `_post_run_digest` (`cli.py:322`, `cli.py:423`) без изменений.
- `src/emerge_ai/state.py`: `RunState.changelog: str | None = None` (`state.py:41-51`); `load_run` (`state.py:83-85`) обратно совместим.
- `src/emerge_ai/changelog.py`: необязательный параметр перечня собранных пакетов в `collect_digest`/`llm_digest` (`changelog.py:98-151`).
- Тесты (`tests/test_cli_integration.py`, тесты changelog), README, `LIVE_CHECKS.md`; закрытие M11 в `REVIEW_NOTES.md`.
