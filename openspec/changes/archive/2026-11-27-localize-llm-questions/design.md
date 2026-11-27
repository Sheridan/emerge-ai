# Design

## Context

Мотивация — в proposal.md. Состояние кода: `ASK_TOOL_SPEC` (`agent.py`) описывает
инструмент `ask_operator` английской строкой без указания языка human-полей;
`ASK_DIRECTIVE_INTERACTIVE` требует сам канал, но тоже молчит о языке; `tool_specs()`
собирает payload, `propose()` вызывает её без знания языка, хотя `self.context["language"]`
уже содержит нормализованное значение (`cli._maybe_agent` → `collect_context(cfg.resolved_language())`).

## Goals / Non-Goals

**Goals:**

- Модель формулирует вопрос/варианты на целевом языке; машинные поля не двигаются.
- При английском языке промпт побайтно прежний (нет двойной директивы, нет шума).

**Non-Goals:**

- Локализация интерфейсных строк emerge-ai, ошибок `validate_question` (тексты к модели),
  каналов not-LLM (consent-меню программы, вопросы исчерпания лимита).

## Decisions

### D1. Указание в описании инструмента, а не в system-промпте

Корень бага — модель считает аргументы tool-call машинными; точечная подсказка живёт там,
где модель решает содержимое полей: `tool_specs(interactive, language)` дописывает в
`description` `ask_operator` фразу «Write the operator-facing text — 'question', each
option's 'label' and 'consequences' — in <Language>; JSON keys, whitelist 'key' values and
commands stay exactly as specified.» при языке ≠ английский (проверка `lower().startswith("en")`).
System-промпт уже несёт общую директиву; дублировать её в интерактивную директиву — шум.

### D2. Фолбэк English = отсутствие правки

`ask_language_note(language)` возвращает `""` для пустого/английского значения — payload
остается прежним байт-в-байт; unknown-языки получают фразу как есть (модель понимает
названия языков). Тесты: en-описание == константа; ru — содержит фразу; propose(interactive)
передаёт язык из context (сквозной scripted-тест через `tools_seen`).

## Risks / Trade-offs

- [Модель всё равно ответит по-английски] → live-проверка в LIVE_CHECKS; при надобности
  фраза продублируется в ASK_DIRECTIVE_INTERACTIVE (следующий шаг, не сейчас).

## Migration Plan

Нет изменений конфига/протокола; откат — откат коммита.

## Open Questions

- Нет.
