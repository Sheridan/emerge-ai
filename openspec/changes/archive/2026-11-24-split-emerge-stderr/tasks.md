# Tasks

## 1. Раздельный захват в runner

- [x] 1.1 В `run_emerge_capturing` (`runner.py:32-50`) убрать `stderr=subprocess.STDOUT`, передать `stderr=subprocess.PIPE`; завести два daemon-потока чтения: stdout-строки → `sys.stdout`, stderr-строки → `sys.stderr`, обе с flush и без изменений байт в байт
- [x] 1.2 Общий буфер: ANSI-stripped-копии обеих сторон дописывать в один `list[str]` под `threading.Lock`, порядок — по факту прочтения; вернуть `(rc, "".join(buffer))` после `proc.wait()`; сигнатура не меняется
- [x] 1.3 Исключения потоков чтения не глушить: складывать в общий slot, после `wait()` пробрасывать наружу; unit-тест с потоком, бросающим ошибку на второй строке

## 2. Тесты

- [x] 2.1 Стаб-emerge в `tests/test_runner.py` пишет различимые строки в stdout и stderr; тест: stdout emerge-ai содержит только stdout-строки, stderr emerge-ai — только stderr-строки, обе без изменений (включая ANSI)
- [x] 2.2 Тест полноты буфера: обе стороны присутствуют в возвращаемом тексте; тест мертлока: стаб печатает большой объём (>pipe buffer) в оба потока, прогон завершается
- [x] 2.3 Прогнать `tests/test_cli_integration.py` и `tests/test_replay_e2e.py`: ассерты incident/enrich/hook на тексте не сломались; при наличии ассертов «stderr-текст в stdout» — инвертировать по новому контракту

## 3. Документация и живой чек

- [x] 3.1 `LIVE_CHECKS.md`: добавить проверку `emerge-ai -av 2>/dev/null` — в stdout нет строк, которые portage писал в stderr; `emerge-ai -av 1>/dev/null` — сообщения stderr там же
- [x] 3.2 Полный `pytest` зелёный; CHANGELOG-заметка (в релиз-нотах пакета) о смене маршрутизации stderr
