# Proposal

## Why

Прогон молчалив: между «emerge запущен» и итоговым дайджестом пользователь не видит, чем
занято приложение. Запуск emerge (`runner.run_emerge_capturing`), каждый HTTP-вызов к LLM
(`LLMClient.chat`), каждый tool-call агента (`grep_log`, `pretend_emerge`, `web_fetch`, …),
починки из белого списка (`emaint`, `emerge --deselect`, правки `package.*`) и команды
защиты/отката выполняются без единой строки «что происходит сейчас»; при `-v` тело запроса
к LLM не показано вовсе. Пользователь не может ни понять, на чём встал прогон, ни воспроизвести
обращение к эндпоинту.

## What Changes

- Перед каждым значимым действием emerge-ai печатает в stderr короткую строку активности
  (`emerge-ai: запускаю: emerge …`, `emerge-ai: отправляю запрос к LLM (model=…, N сообщений,
  tools=M)`, `emerge-ai: tool: grep_log(…)`, `emerge-ai: fetch: <url>`). Это уровень по
  умолчанию: коды выхода, сквозной pass-through stdout emerge и существующие информационные
  строки не меняются.
- При `-v`/`--verbose` (включая кластеры) поверх анонсов: тело каждого запроса к эндпоинту
  (JSON с капом и плашкой усечения, значение API-ключа вырезано) и длительность вызова.
- Тривиальные read-only пробы окружения (`findmnt`, чтение `/proc`) строк активности не
  порождают.
- Вне scope: вывод рассуждений модели (изменение `fix-verbose-thinking-output`), язык ответов
  (изменение `fix-llm-response-language`), лог-файлы/JSON-релоги.

## Capabilities

### New Capabilities

- `progress-logging`: отображение текущей деятельности emerge-ai — строки активности по
  умолчанию, дампы запросов и длительности при `-v`, дисциплина секретов и шума,
  совместимость со сквозным pass-through emerge и console-output.

### Modified Capabilities

<!-- нет: поведение строк активности описывается новой capability -->

## Impact

- `src/emerge_ai/ui.py` — хелпер строк активности (`activity`, info-стиль, plain в pipe).
- `src/emerge_ai/llm.py` — `chat()`: анонс запроса, verbose-дамп payload (cap, маскирование
  ключа), строка длительности; флаг конструктора `show_reasoning` переименовывается в
  `verbose` (он включает не только рассуждения).
- `src/emerge_ai/runner.py` — анонс полного argv перед каждым Popen emerge.
- `src/emerge_ai/agent.py`, `sandbox.py` — анонс tool-call'ов с аргументами (кап ~200 симв.),
  web-fetch с URL.
- `src/emerge_ai/whitelist.py`, `rollback.py`, `config_edit.py` — анонсы команд починок,
  защиты и отката.
- Тесты (`test_ui`, `test_llm`, `test_runner`, `test_agent`, `test_cli`, `test_whitelist`,
  `test_rollback`, `test_config_edit`), README (раздел активности/`-v`), `LIVE_CHECKS.md`.
