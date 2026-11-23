# Proposal

## Why

Вывод emerge-ai в терминал полностью monochrome (кроме одного безусловно-применяемого dim для reasoning): сообщения об ошибках, tier-риски плана, диффы конфигов и текст LLM визуально неотличимы друг от друга. При этом в вывод LLM просачивается markdown по умолчанию модели, а ANSI-коды крашеного emerge попадают в промпты LLM и ломают разбор захваченного вывода (регулярки `post_run_digest` не совпадают с `[ebuild`-строками на живом emerge).

## What Changes

- Новый модуль терминального оформления: включение цвета = `isatty` && `NO_COLOR` не задан && `TERM != dumb`; в pipe/redirect — всегда plain. Только stdlib (ANSI-константы), без новых зависимостей.
- Фиксированная палитра для собственных сообщений emerge-ai: ошибки red, предупреждения yellow, успех green, tier-строки plan digest/doctor от red (tier 1) до dim (tier 5), `+`/`-` в etc-диффе green/red, промпты подтверждения bold/yellow.
- Общий рендерер LLM-блоков во всех трёх местах показа (`llm.render`, agent proposal в CLI, changelog digest в CLI): `content`, `reasoning` (бледным) и строки-вопросы с маркером `QUESTION:` окрашиваются цветами из новой опции конфига `llm_colors`; невалидное имя цвета — предупреждение и дефолт.
- Конвенция маркера `QUESTION:` в системном промпте агента для вопросов оператору (внутри free-form текста; интерактивного Q&A-канала не появляется).
- Инструкция «plain text, no markdown» в промпты, чей вывод видит пользователь (агент, changelog-digest); markdown-рендеринга и sanitizer-а нет.
- Снятие ANSI с вывода emerge/journalctl на входе в LLM: `stderr_tail` инцидента, результаты `pretend_emerge`/`journal_search`. Побочно чинит regex-разбор `[ebuild`/`>>> Emerging` в post-run digest на крашеном выводе.
- Вывод emerge (passthrough) не изменяется: emerge-ai не добавляет и не удаляет коды в собственном потоке emerge.

## Capabilities

### New Capabilities

- `console-output`: правила включения/палитры терминального вывода emerge-ai, окраска собственных сообщений и LLM-блоков (включая `QUESTION:`), plain-text вывод LLM, снятие ANSI на входе в LLM.

### Modified Capabilities

- `config-prompts`: схема конфигурации пополняется опцией `llm_colors` (палитра для LLM-блоков; whitelist имён цветов, невалидное значение — warn + дефолт).
- `agent-loop-consent`: агент обязан уметь задавать вопросы оператору маркированной строкой `QUESTION:` в выходном тексте и отвечать plain text без markdown.

## Impact

- Код: новый модуль (ui/стили) в `src/emerge_ai/`; `cli.py` (~39 print-точек), `llm.py`, `digest.py`, `enrich.py`, `doctor.py`, `etcupdate.py`, `changelog.py`; `incident.py` и `sandbox.py` (ANSI-strip); `agent.py`/`changelog.py` (правки system-промптов); `config.py` (`llm_colors` в DEFAULTS + валидация).
- Зависимости: нет новых (stdlib-only сохранён).
- Тесты: capsys-вывод не-tty → plain, существующие тесты не ломаются; добавляются тесты детекта tty/NO_COLOR, палитры, strip-а и конфига.
- Спецификация emerge-флага `-v`/управления reasoning не меняется — цвет лишь оформление.
