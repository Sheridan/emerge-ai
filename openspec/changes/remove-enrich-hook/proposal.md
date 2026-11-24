# Proposal

## Why

Модуль `src/emerge_ai/hooks.py` — мёртвый API из трёх функций (`Hook`, `set_hook`,
`run_hook`): docstring `set_hook` обещает «регистрирует хук, вызываемый перед enrich
(напр. Telegram-уведомление)», но ни одна спецификация (в т.ч. уведомлений) этот hook
не описывает, и в README он не документирован. `set_hook` в продакшне не вызывается
никогда (единственные вызовы — в тесте), поэтому `run_hook(notify.get("pkg"), "pre-enrich", ...)`
в `_run_pool` (`src/emerge_ai/cli.py:359`) — всегда no-op: реальное enrich-уведомление
вешалось напрямую, а не через эту точку. Механизм, который по замыслу должен был быть
точкой расширения, стал декорацией (REVIEW_NOTES M7).

## What Changes

- **BREAKING** — удаление неописанного API (`hooks.Hook`/`set_hook`/`run_hook`): публично
  не документирован (ни README, ни specs), внешних потребителей в репозитории нет.
- Модуль `src/emerge_ai/hooks.py` удалён; удалён импорт `from .hooks import run_hook`
  (`cli.py:11`) и вызов в `_run_pool` (`cli.py:359`).
- Тест `test_pretend_prints_verbatim_runs_once_and_fires_hook` (`tests/test_cli.py:35-46`)
  **переписан, а не удалён**: он покрывает ценное поведение — `--pretend` печатает
  stdout эмуляции дословно (assert'ы на точный текст) и запускает emerge ровно один раз;
  убраны только hook-assert'ы (`calls`) и импорт `set_hook` (`tests/test_cli.py:5`).

## Capabilities

### Modified Capabilities

(нет) — `grep -rn "hooks" openspec/specs README.md` пуст: ни одна спецификация и README
не ссылаются на hook-механизм; поведение `--pretend` (дословный вывод, один запуск)
специфицировано независимо от hook'ов и не меняется. Удаление мёртвого кода →
`skip_specs: true`.

## Impact

- **Код**: удаление `src/emerge_ai/hooks.py`; `src/emerge_ai/cli.py` (`:11`, `:359`).
- **Тесты**: `tests/test_cli.py` — переименование/переписывание hook-теста, удаление
  импорта `:5`.
- **Docs**: README hook'и не упоминает — без изменений.
- **Зависимости**: независимо; смежно с `remove-unused-run-emerge` (тот же класс чисток
  в `cli.py`; `_run_pool` другими change'ами не правится).
