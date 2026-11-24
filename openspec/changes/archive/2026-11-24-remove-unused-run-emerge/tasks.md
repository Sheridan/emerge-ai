# Tasks

## 1. Удаление

- [x] 1.1 `grep -rn "run_emerge" src/ tests/ README.md openspec/ | grep -v run_emerge_capturing`
      — убедиться, что владения только `runner.py:14` (определение) и `cli.py:23` (импорт)
- [x] 1.2 Удалить `run_emerge` из `src/emerge_ai/runner.py` (`:14-16`); `EMERGE` и
      `run_emerge_capturing` не трогать
- [x] 1.3 Убрать `run_emerge` из импорта `from .runner import ...` (`cli.py:23`)

## 2. Проверка

- [x] 2.1 `pytest` полностью зелёный; `python -c "import emerge_ai.cli, emerge_ai.runner"`
      без ошибок
- [x] 2.2 CHANGELOG в репозитории нет — удаление `runner.run_emerge` (BREAKING неописанного
      API) отметить в сообщении коммита/PR
- [x] 2.3 `openspec validate "remove-unused-run-emerge"`
