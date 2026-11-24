# Proposal

## Why

`_etc_flow` (`src/emerge_ai/cli.py:145`) принимает `confirm_fn` третьим позиционным
параметром и никогда не обращается к нему в теле. Фактическое подтверждение каждого
решения идёт через `etcupdate.apply_decision`, которой в `cli.py:196` жёстко передаётся
no-op `confirm_fn=lambda _p: True` (у `apply_decision` это обязательный keyword — реальный
гейт перед мутацией файла). Продакшн-коллауты при этом передают константы:
raw-passthrough-режим — `lambda _p: False` (`cli.py:320`, поток с `llm=False` выходит до
решений), основной путь — настоящую `confirm` (`cli.py:421`), которую функция игнорирует.
Параметр создаёт ложное ожидание, что подтверждение по каждому файлу управляется
оператором, хотя единственный диалог — промпт «Apply LLM decision [Y/n/c…]»
(`cli.py:188-190`, `input_fn` + `parse_override`). REVIEW_NOTES M6.

## What Changes

- **BREAKING** — нет: `_etc_flow` — внутренняя функция (не в README/specs), поведение
  CLI не меняется, меняется только её сигнатура.
- Параметр `confirm_fn` удалён из сигнатуры `_etc_flow` (`:145`) вместе с аргументами в
  двух коллаутах (`:320`, `:421`).
- No-op `confirm_fn=lambda _p: True` в вызове `apply_decision` (`:196`) сохранён — это
  обязательный keyword гейт `apply_decision`, — но снабжён комментарием, что это осознанно:
  единственное подтверждение уже произошло выше через `input_fn`.
- Тесты, вызывающие `_etc_flow(confirm_fn=lambda p: True)` (`tests/test_etcupdate.py:129`,
  `:143`, `:159`), теряют аргумент; прямые тесты `apply_decision` (`:89`, `:92`) не трогаются.

## Capabilities

### Modified Capabilities

(нет) — ни один текст требований не ссылается на этот параметр: контракт подтверждения
etc-update в спеках зафиксирован через промпт `input_fn` и гейт `apply_decision`, а не
через механизм проброса колбэка в `_etc_flow`. Удаление мёртвого кода не меняет
требований → `skip_specs: true`.

## Impact

- **Код**: `src/emerge_ai/cli.py` (`:145`, `:320`, `:421`; комментарий у `:196`).
- **Тесты**: `tests/test_etcupdate.py` — убрать `confirm_fn=` из трёх вызовов `_etc_flow`;
  поведение покрывают существующие тесты (diff-only, merge+citations, override).
- **Docs**: README `confirm_fn` не упоминает — без изменений.
- **Зависимости**: независимо; смежно с `fix-etc-web-fetch-stub` и `etc-update-language`
  (тот же `_etc_flow`), пересечения по смыслу нет.
