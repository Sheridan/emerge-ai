# Tasks

## 1. Строки активности (`ui.activity`, внешний мир)

- [x] 1.1 `ui.activity(msg, stream=sys.stderr)` — строка `emerge-ai: <msg>` в info-стиле
      (console-output: без цветового акцента, plain в pipe); юниты в `test_ui.py`
      (TTY/pipe/NO_COLOR).
- [x] 1.2 `runner.run_emerge_capturing` — анонс `запускаю: emerge <полный argv>` до Popen
      (включая ретраи с env-оверрайдами); юнит в `test_runner.py` (анонс в stderr, stdout не
      тронут); существующие тесты `split-emerge-stderr` остаются зелёными.
- [x] 1.3 Анонсы tool-call'ов: `agent._dispatch.call` — `tool: <name>(<args>, кап ~200
      символов)` до исполнения; `sandbox.web_fetch` — `fetch: <url>`; юниты в
      `test_agent.py`/`test_sandbox_injection.py` (строка есть до результата, кап аргументов).
- [x] 1.4 Анонсы команд починок/защиты/отката: `whitelist.execute` (emaint/deselect —
      полный argv), `rollback` (btrfs и пр.), правки `config_edit` (какой файл/строка);
      `prompts._run` (findmnt, /proc) — молчит; юниты в `test_whitelist.py`,
      `test_rollback.py`, `test_config_edit.py`.

## 2. Видимость обращений к LLM (`llm.py`)

- [x] 2.1 `LLMClient.show_reasoning` → `verbose` (конструктор + все call-site'ы `cli.py`,
      `test_llm.py`); поведение пока прежнее; тесты `test_llm.py` зелёные.
- [x] 2.2 Анонс и длительность в `chat()`: до запроса `отправляю запрос к LLM (model=…,
      N сообщений, tools=M)`, после — `ответ LLM за X.Xs (finish=…)`; stream — stderr с
      тестируемым швом; юниты (сфейковый urlopen): строки есть, порядок «анонс → ответ».
- [x] 2.3 Verbose-дамп payload в `chat()`: JSON тела запроса, cap константой модуля с
      плашкой `[capped …]`, значение `api_key` в дампе → `***`, заголовки не дамперятся;
      без `-v` дампа нет; юниты в `test_llm.py` (маскирование ключа, кап, отсутствие дампа).
- [x] 2.4 Проводка verbose в забытые места: `_post_run_digest`/changelog-клиент получают
      verbose из `main`; интеграционный тест `test_cli.py` (фейковый endpoint): при `-v`
      дамп запроса сводки дайджеста в stderr, без `-v` — нет.

## 3. Документация и live-проверки

- [x] 3.1 README: раздел об активности (анонсы всегда; дампы запросов и длительности — под
      `-v`; только stderr; предупреждение, что дампы содержат приватный текст) — вычитка
      глазами; `pytest` не затрагивается.
- [x] 3.2 `LIVE_CHECKS.md`: ручные проверки — `emerge-ai -p <атом> -v` (анонсы emerge/LLM +
      JSON запроса с капом), `emerge-ai -a <атом>` (анонсы есть, тел запросов нет),
      `api_key` в конфиге (`***` в дампе).
- [x] 3.3 Прогон `pytest` + `openspec validate add-progress-logging --strict` — зелёные;
      сценарии спека progress-logging покрыты тестами групп 1–2.
