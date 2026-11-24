# Tasks

## 1. Удаление параметра

- [x] 1.1 `grep -rn "confirm_fn" src/ tests/` — зафиксировать владения: `_etc_flow`
      (`cli.py:145,:320,:421`), гейт `apply_decision` (`cli.py:196`, `etcupdate.py`,
      `tests/test_etcupdate.py:89,:92`) и три теста `_etc_flow` (`:129,:143,:159`)
- [x] 1.2 Убрать `confirm_fn` из сигнатуры `_etc_flow` (`cli.py:145`) и аргументы из
      коллаутов `:320` (`lambda _p: False`) и `:421` (`confirm=confirm`)
- [x] 1.3 В `:196` сохранить `confirm_fn=lambda _p: True` и добавить комментарий:
      единственное подтверждение уже выполнено выше через `input_fn`/`parse_override`

## 2. Тесты и проверка

- [x] 2.1 `tests/test_etcupdate.py`: убрать `confirm_fn=lambda p: True` из трёх вызовов
      `_etc_flow` (`:129`, `:143`, `:159`); вызовы `apply_decision` (`:89`, `:92`) не трогать
- [x] 2.2 `pytest` полностью — etc-тесты (diff-only, merge+citations, override) зелёные;
      `grep -n confirm_fn src/emerge_ai/cli.py` оставляет только строку `:196`
- [x] 2.3 `openspec validate "fix-etc-confirm-fn"`
