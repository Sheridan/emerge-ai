# Proposal: emerge-color-through-capture

## Why

После add-colorized-output собственный вывод emerge-ai окрашен, но вывод самого `emerge` в терминале остаётся plain: `run_emerge_capturing` запускает emerge с `stdout=PIPE` (нужен захват для digest/incident), portage в auto-режиме не видит TTY и никогда не красит. Требование «собственная раскраска emerge не трогается» сейчас тривиально выполняется над пустотой — красить нечего.

## What Changes

- `runner.run_emerge_capturing`: при цветном выводе emerge-ai (stdout — TTY, `NO_COLOR` не задана, `TERM != dumb` по правилам `ui.supports_color`) подставлять в аргументы emerge `--color=y`; если `--color` уже задан пользователем — не вмешиваться. В uncaptured `run_emerge` stdio наследуется, автоопределение portage работает — подстановка не нужна.
- Пасsthrough остаётся побайтовым: emerge-ai по-прежнему не добавляет и не удаляет коды из строк emerge; меняется только команда запуска.

## Capabilities

- `console-output`: новая requirement — emerge-ai сам включает раскраску emerge при цветном выводе.

## Impact

- `src/emerge_ai/runner.py` (+хелпер подстановки), тесты `tests/test_runner.py`, `tests/test_cli_integration.py`.
- Поведение в pipe/CI/`NO_COLOR` не меняется (plain); argv emerge в TTY получает дополнительный `--color=y`.
