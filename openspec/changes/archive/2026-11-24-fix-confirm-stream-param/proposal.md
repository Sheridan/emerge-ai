# Proposal

## Why

`runner.confirm` объявлен как `confirm(prompt="Proceed? [y/N] ", stream=sys.stdin)` (`src/emerge_ai/runner.py:53`), но `stream` в теле не используется — внутри голый `input()` (`runner.py:56`), который всегда читает `sys.stdin`. Подпись обещает инъектируемость потока, которой нет (REVIEW_NOTES L2, `REVIEW_NOTES.md:191-194`); оба вызова — `cli.py:371` и `cli.py:401` — параметр не передают, тесты подтверждают согласие через патч `builtins.input`. Мёртвый параметр ввёд в заблуждение: читающий код предполагает, что поток можно подменить, — это не так.

## What Changes

- У `runner.confirm` удаляется параметр `stream` — сигнатура становится `confirm(prompt: str = "Proceed? [y/N] ") -> bool`.
- Поведение не меняется: тот же `input()`, EOF по-прежнему трактуется как «нет», те же ответы `y`/`yes`.
- Аргумент `stream=sys.stdin` из сигнатуры и связанный импорт-зависимость (если `sys` в runner больше не нужен — остаётся: он используется в `run_emerge_capturing`) убираются; docstring уточняет, что поток — `sys.stdin`, подменяется патчем `builtins.input`.
- Вызывающий код (`cli.py:371`, `cli.py:401`) не меняется — он параметр не передавал.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

(нет — поведение подтверждения не меняется, меняется только внутренняя сигнатура; спецификации не затрагиваются, `skip_specs: true`)

## Impact

- `src/emerge_ai/runner.py:53-58` — сигнатура `confirm`.
- `src/emerge_ai/cli.py:371`, `src/emerge_ai/cli.py:401` — без изменений (параметр не использовался).
- Тесты: `grep` по `tests/` не оставляет вызовов `confirm(stream=...)`; паттерн «патчить `builtins.input`» остаётся единственным seam — тесты править не нужно.
- `REVIEW_NOTES.md` L2 закрывается.
