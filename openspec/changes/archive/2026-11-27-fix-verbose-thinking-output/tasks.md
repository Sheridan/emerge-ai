# Tasks

## 1. Печать рассуждений в `chat()`

- [x] 1.1 `LLMClient.chat()` печатает `[reasoning]` при флаге verbose-рассуждений и непустом
      `reasoning_content` (stderr, палитра `llm_colors.reasoning`, plain в pipe); юниты
      `test_llm.py`: печать появилась, без флага — тишина, палитра/`off` работают.
- [x] 1.2 `LLMClient.render()` — только content (reasoning-ветка удалена);
      `run_tool_loop`/`render_to` контрактно не меняется; обновлённый
      `test_llm.py::test_render_reasoning_only_when_enabled` + новый тест «прямой chat без
      tool-цикла показывает reasoning».
- [x] 1.3 Тест отсутствия дублей: fake-клиент с двумя ответами, содержащими reasoning, через
      `run_tool_loop` с `render_to` — каждый `[reasoning]` ровно один раз; юнит в
      `test_llm.py`.

## 2. Проводка verbose

- [x] 2.1 `_post_run_digest` получает verbose из `main` и строит changelog-`LLMClient` с
      ним; интеграционный тест `test_cli.py` (фейковый endpoint с `reasoning_content`): при
      `-v` reasoning сводки дайджеста/changelog в stderr, без `-v` — нет; существующие тесты
      «нет endpoint / сбой LLM» не изменились.

## 3. Документация и live-проверки

- [x] 3.1 README: вывод рассуждений — при `-v` на каждом обращении к модели (агент, сводки,
      consent, etc-update, changelog); вычитка глазами.
- [x] 3.2 `LIVE_CHECKS.md`: `emerge-ai -p <атом> -v` — `[reasoning]` сводки дайджеста виден
      в stderr; `emerge-ai -p <атом>` — нет; agent-петля (сбойный атом) — каждое рассуждение
      ровно один раз.
- [x] 3.3 Прогон `pytest` + `openspec validate fix-verbose-thinking-output --strict` —
      зелёные; сценарии дельты config-prompts покрыты тестами групп 1–2.
