# Proposal

## Why

`run_emerge_capturing` запускает emerge с `stderr=subprocess.STDOUT` (`src/emerge_ai/runner.py:40`) и зеркалит весь объединённый поток в `sys.stdout` (`runner.py:45-47`). Штатный путь `-p`/`-a` и plan-фаза (`src/emerge_ai/cli.py:333`, `cli.py:410`) идут только через этот захват, поэтому stderr emerge всегда попадает в stdout emerge-ai. Это ломает разделение потоков у потребителя (`emerge-ai ... 2>/dev/null`, `| grep`-пайплайны) и делает ложью обещание спека console-output о том, что вывод emerge «передаётся без изменений» (`openspec/specs/console-output/spec.md:84-88`): строки, которые emerge пишет в stderr, оказываются в чужом потоке. Захват и общий буфер необходимы (incident/enrich читают текст вывода), но маршрутизировать строки по исходным потокам ничто не мешает.

## What Changes

- `run_emerge_capturing` захватывает stdout и stderr emerge раздельно; stdout-строки зеркалятся в `sys.stdout`, stderr-строки — в `sys.stderr` (обе — без изменений байт в байт, включая ANSI emerge).
- Возвращаемый буфер остаётся одним объединённым текстом (incident, enrich, hooks потребляют именно его); порядок строк из разных потоков — по факту прочтения и не гарантирован.
- **BREAKING** для скриптов, которые парсили stderr emerge в stdout emerge-ai: stderr emerge больше не появляется в stdout.
- Код возврата emerge и формат возвращаемого `(rc, output)` не меняются; подстановка `--color=y` (`runner.py:19-29`) не меняется.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `console-output`: добавляется требование разделения потоков emerge при захвате (stderr в stderr, stdout в stdout, чистота stdout passthrough); существующие требования про passthrough и окраску сквозь захват сохраняют силу.

## Impact

- `src/emerge_ai/runner.py`: `run_emerge_capturing` — два потока чтения вместо слияния (`stderr=STDOUT` уходит), общий буфер под локом.
- `src/emerge_ai/cli.py`: не меняется (возвращаемый контракт тот же), но затронуты все ветки вывода: plan-фаза, merge под `-a`, ветки incident.
- `tests/test_runner.py`, `tests/test_cli_integration.py`: стабы emerge должны писать различимые строки в оба потока; ассерты «stderr-текст в stdout» (если есть) инвертируются.
- `LIVE_CHECKS.md`: живой чек `emerge-ai -av 2>/dev/null` — в stdout не должно stderr-строк portage.
