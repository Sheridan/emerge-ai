# Tasks

## 1. Удаление модуля

- [x] 1.1 `grep -rn "hooks\|run_hook\|set_hook" src/ tests/ README.md openspec/` —
      убедиться, что владения только `cli.py:11,359` и `tests/test_cli.py:5,38,42`
- [x] 1.2 Удалить `src/emerge_ai/hooks.py`, импорт `run_hook` (`cli.py:11`) и вызов
      `run_hook(...)` в `_run_pool` (`cli.py:359`)

## 2. Переписывание теста

- [x] 2.1 `tests/test_cli.py`: в `test_pretend_prints_verbatim_runs_once_and_fires_hook`
      (`:35-46`) убрать `calls`/`set_hook`/assert хука и импорт (`:5`); сохранить assert'ы
      дословного вывода и одного запуска; переименовать в
      `test_pretend_prints_verbatim_runs_once`

## 3. Проверка

- [x] 3.1 `pytest` полностью зелёный; `python -c "import emerge_ai.cli"` без ошибок;
      `grep -rn hooks src/ tests/` пуст
- [x] 3.2 `openspec validate "remove-enrich-hook"`
