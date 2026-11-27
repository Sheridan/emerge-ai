# Proposal

## Why

Thinking не виден в verbose-режиме. Эндпоинт `reasoning_content` отдаёт по умолчанию
(проверено живым запросом к strata), но блок `[reasoning]` печатает только `run_tool_loop`
через `LLMClient.render` — то есть исключительно в agent-петле разбора инцидентов. Все
прочие обращения к модели — сводка дайджеста, news, анализ consent-меню, разбор config-файлов
(`etcupdate.llm_decide`), changelog-дайджест — зовут `client.chat()` напрямую и рассуждения
выбрасывают: при `-v` пользователь думает, что thinking «не выводится», хотя он просто нигде
не печатается, кроме одного узкого пути.

## What Changes

- Печать `[reasoning]` переносится в `LLMClient.chat()`: каждый ответ эндпоинта с
  рассуждениями показывает их при `-v` — на любом виде вызова, включая будущие новые
  call-site'ы без дополнительной проводки.
- `LLMClient.render()` печатает только content — в tool-цикле рассуждения не дублируются
  (каждый ход модели показан ровно один раз); контракт `run_tool_loop` не меняется.
- Без `-v` рассуждения не печатаются, как и сейчас (spec: config-prompts).
- `_post_run_digest`/changelog-клиент получают verbose из `main` — единственное место, где
  флаг терялся.
- Вне scope: строки активности и дампы запросов (`add-progress-logging`), язык ответов
  (`fix-llm-response-language`).

## Capabilities

### New Capabilities

<!-- нет -->

### Modified Capabilities

- `config-prompts`: требование «Вывод рассуждений» — обязательность показа при `-v` не
  зависит от вида LLM-вызова; ровно один блок на ответ эндпоинта; без `-v` — скрыты.

## Impact

- `src/emerge_ai/llm.py` — `chat()` печатает `[reasoning]` (при verbose, палитра
  `llm_colors.reasoning`); `render()` — только content.
- `src/emerge_ai/cli.py` — `_post_run_digest` получает verbose и передаёт его
  changelog-клиенту.
- Тесты (`test_llm` — печать в chat, отсутствие дублей в tool-цикле; `test_cli` — reasoning
  сводки дайджеста в stderr при `-v`), README (уточнение «на каждом вызове»), `LIVE_CHECKS.md`.
- Пересечение с `add-progress-logging` — тот же `chat()`, но поведения не касаются:
  изменения независимы, порядок применения любой.
