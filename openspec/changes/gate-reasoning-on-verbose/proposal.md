# Proposal

## Why

Показ рассуждений модели сейчас — это конфиг-опция `reasoning_show` (default: вкл), т.е. скрытный diagnostic-вывод включён по умолчанию у всех, а пользователям приходится править root-конфиг `/etc/portage/emerge-ai.json`, чтобы его отключить/включить. verbosity — штатная семантика emerge-флага `-v`/`--verbose`; логично привязать отладочный вывод рассуждений к нему и убрать лишнюю опцию из поверхности конфигурации.

## What Changes

- **Удаление опции** `reasoning_show` из конфигурации: убрать из `DEFAULTS`/`Config` (`config.py`), из схемы спеки `config-prompts`, из README и документации конфига. Строка `"reasoning_show": ...` в существующих конфигах не ломает запуск: к общему предупреждению «ignoring unknown key» добавляется целенаправленное — «удалён; управляется флагом -v/--verbose».
- **Новое поведение**: `LLMClient.render` печатает `[reasoning] ...` только когда в argv emerge присутствует `-v` или `--verbose` (распознавание cluster-aware: `-av`, `-pv` — как `flag_present` для pretend/ask); по умолчанию (без `-v`) рассуждения не печатаются **даже если эндпоинт их отдаёт**.
- Флаг `-v`/`--verbose` остаётся чистым passthrough: emerge-ai читает его для своего diagnostic-режима, но не вырезает из argv.
- Проброс verbosity до мест создания `LLMClient` в `cli.py` (`_make_tier_service`, `_maybe_agent`, `_changelog_mode`, `_etc_flow` — через явный параметр).

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `config-prompts`: «Конфигурационный файл» — из схемы удалён `llm.reasoning_show`; «Вывод рассуждений» — привязка к `-v`/`--verbose` (включая кластеры) вместо конфиг-опции, default — выключен.

## Impact

- Код: `src/emerge_ai/config.py` (удаление ключа + deprecation-warning), `src/emerge_ai/llm.py` (`LLMClient` получает явный признак verbosity), `src/emerge_ai/cli.py` (детект `verbose` рядом с `pretend`/`ask`, проброс в фабрики клиентов), `tests/test_config.py`, `tests/test_llm.py`, тесты CLI; `README.md` (секция конфига), при необходимости `packaging/emerge-ai.json.default` (ключа нет — проверено).
- Пересечение с in-flight change `refactor-cli-flag-parsing`: тот же `cli.py`, но ортогонально (verbose — emerge-флаг, не own-flag); любой порядок применения сохраняет зелёные тесты, если каждый change прогоняет полный pytest после своего.
- **Совместимость**: поведение меняется по умолчанию — конфиг с `reasoning_show: true` больше НЕ включает вывод без `-v`; разрушающее изменение surface'а конфига, согласованное с запросом.
