# Proposal

## Why

`run_emerge` (`src/emerge_ai/runner.py:14-16`) — тонкая обёртка `subprocess.run([EMERGE,
*args])` без захвата вывода, «для live-режима / ручных сценариев». Фактически не
используется нигде: CLI вызывает только `runner.run_emerge_capturing` (`src/emerge_ai/cli.py:260,313`)
и `runner.EMERGE` (`cli.py:266,326,384`); в `cli.py:23` импортирован неиспользуемый
`run_emerge`. Единственные упоминания имени в тестах — подстроки `run_emerge_capturing`
(`grep -rn run_emerge tests/ | grep -v capturing` пуст). Мёртвый код в модуле-«обёртке
над emerge» к тому же опасен как приманка: путь без захвата вывода минует разбор
инцидентов, на котором держится весь product-loop (REVIEW_NOTES M8).

## What Changes

- **BREAKING** — удаление неописанного API `runner.run_emerge`: в README и specs не
  упоминается (`grep -rn run_emerge README.md openspec/specs` даёт только подстроки
  `run_emerge_capturing`), внешних потребителей в репозитории нет.
- Функция `run_emerge` удалена из `src/emerge_ai/runner.py` (`:14-16`).
- Неиспользуемый импорт `run_emerge` убран из списка импортов `src/emerge_ai/cli.py:23`.
- Константа `EMERGE` и `run_emerge_capturing` (с `--nodeps`/`--quiet`, захватом вывода
  и лимитом) не затрагиваются.

## Capabilities

### Modified Capabilities

(нет) — спецификации описывают поведение через `run_emerge_capturing` (dry-run через
`--pretend`, live-запуск emerge); сама обёртка `run_emerge` ни в одном требовании не
фигурирует. Удаление мёртвого кода требований не меняет → `skip_specs: true`.

## Impact

- **Код**: `src/emerge_ai/runner.py` (`:14-16`), `src/emerge_ai/cli.py` (`:23`).
- **Тесты**: не требуют изменений — прямых тестов `run_emerge` нет, тесты
  `run_emerge_capturing` не затрагиваются.
- **Docs**: README `run_emerge` не упоминает — без изменений.
- **Зависимости**: независимо; смежно с `remove-enrich-hook` (одна волна чисток).
