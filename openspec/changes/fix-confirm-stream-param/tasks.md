# Tasks

## 1. Правка

- [x] 1.1 `runner.py:53`: убрать `stream=sys.stdin` из сигнатуры `confirm`; тело не трогаем (`input(prompt)`, `EOFError → False`)
- [x] 1.2 Docstring: зафиксировать, что читается `sys.stdin` через `input()`, тестовый seam — патч `builtins.input` (design D2)

## 2. Проверки

- [x] 2.1 `grep -rn "confirm(" src tests` — ни одного вызова с `stream=`; `cli.py:371`, `cli.py:401` не менялись
- [x] 2.2 Полный `pytest` зелёный без правок тестов (согласие и так патчит `builtins.input`)
- [x] 2.3 Ручной чек: `emerge-ai -a app-editors/vim` с ответом `n` → abort rc=0; EOF (закрытый stdin) → считается «нет»

## 3. Документы

- [x] 3.1 `REVIEW_NOTES.md` L2 пометить закрытым
