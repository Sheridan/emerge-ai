# Design

## Context

Мотивация — в proposal.md (Why). Текущее состояние, влияющее на подход:

- Единственный модуль стилизации — `ui.py` (`paint`/`color_sgr`/`supports_color`, whitelist
  `COLOR_SGR`, `TIER_GRADIENT`); спека `console-output` запрещает ad-hoc escape-коды и требует
  plain в pipe/`NO_COLOR`/`TERM=dumb`.
- Три рендерера блоков выбора: `ui.render_question` (stderr агента, paint уже есть),
  `gate.render` (возвращает строку, не знает про stream, красок нет) и `consent.render_question`
  (собирает contract + `gate.render` в один string, печатается `echo` в `plan_stream`);
  `gate.gate()` зовёт `render` через `echo=print` (stdout).
- Отчёт `triage.render_report` возвращает список строк, cli печатает их в `plan_stream`;
  дайджест `enrich` печатает kind-токены находок (`  - {kind} …`) внутри `plan_digest(stream=…)`.

## Goals / Non-Goals

**Goals:**
- Единый источник правды для цветов меню и шкалы типов — в `ui.py`, рядом с `TIER_GRADIENT`.
- Различимость блоков и важности периферийным зрением в TTY без изменения текстового смысла
  (в pipe виден тот же контент плюс баннер/разделители).

**Non-Goals:**
- Настройка цветов меню/шкалы конфигом (фиксированная палитра по определению).
- Окраска kind-токенов candidate-фиксов (`+ mask: …`) и `FAILURE_CLASSES` инцидентов — только
  теги находок триажа и дайджеста.
- Ширина баннера по терминалу (ioctl/`shutil.get_terminal_size` не используем).

## Decisions

### D1. Фиксированная палитра вместо `llm_colors`
Оформление блоков решений (баннер, тело, цифры) и шкала типов — фиксированные слоты палитры
собственных сообщений. Альтернатива — брать цвета из `llm_colors.content`/`question` —
отклонена: меню это chrome emerge-ai, а не текст модели; при `content=off` блок потерял бы
выделение, что противоречит цели. Строка вопроса, формулируемого LLM, сохраняет
`llm_colors.question` (дефолт и так yellow — визуальной щели нет).

### D2. Баннер + пустые строки как разделители, видимые и без цвета
Структура блока: пустая строка, баннер, строки вариантов, пустая строка. Баннер — строка-
константа `DECISION_BANNER` фиксированной ширины (≈40 символов) вида
`── decisions ────────────…`; красится `PROMPT_SGR` (bold+yellow, уже существующий слот
промптов). Тело блока — `yellow`, цифры выбора — `green`; метки `[c]`/`[q]` не цифры и остаются
телом. Альтернативы: рамка по ширине терминала (зависимость от окружения, ломает grep),
только цвет без баннера (в pipe/NO_COLOR отделения нет). Печать баннера и пустых строк —
обычные `print`, escape-кодов в plain-режиме не появляется.

### D3. Окраска в момент рендера с явными stream-аргументами
`paint` решает про цвет по stream, поэтому рендереры получают целевой stream параметром:
`gate.render(variants, *, stream=sys.stdout)`, `consent.render_question(..., stream=...)`,
`run_dialog(..., stream=None)`, `triage.render_report(..., stream=None)`; cli передаёт тот же
`plan_stream`, в который печатает. Числа красятся отдельным `paint` внутри строки:
`paint(stream, green, "[1]") + paint(stream, yellow, " Title (fix)")`. Альтернатива —
окрашивать на уровне echo по готовым строкам — отклонена: потребовала бы парсинга строк
обратно и путала бы stream решения (stdout) со stream фактической печати (plan_stream).

### D4. Одна карта `KIND_COLORS` в `ui.py`
`KIND_COLORS = {"severity": "red", "dep-conflict": "red", "conflict": "red",
"empty-update": "red", "masked": "yellow", "dep-required": "yellow",
"config-updating": "yellow", "world-file": "yellow", "important": "cyan",
"warning": "cyan"}` и помощник `kind_sgr(kind)` (неизвестный → `""`, как `color_sgr`).
Полосы важности по последствиям, не по каналам portage: красный — блокирующие merge
критичные (`!!!`, конфликты, пустой update); жёлтый — исполняемые условия с whitelisted-фиксом
(masked/dep-required/config-updating/world-file); циан — информационные (`important`,
generic `warning`). `triage` и `enrich` уже импортируют `ui` — общего кода добавляется ноль,
кроме самих вызовов.

### D5. `render_question` остаётся общим рендерером
Тот же блок украшается изнутри `ui.render_question` (баннер/разделители/цвета фиксированные,
вопрос — палитрой). `choice_prompt` (bold yellow) и `echo_answer` (content-палитра) не
меняются: эхо ответа — не часть блока выбора.

## Risks / Trade-offs

- [Точные строки меню закреплены в тестах/докaх] → `test_gate`/`test_consent`/`test_ui` и
  примеры в `README`/`LIVE_CHECKS` обновляются в рамках tasks; это ожидаемый BREAKING формата.
- [Каждый раунд consent-цикла печатает баннер заново] → принято: цикл с вольным текстом
  оператора перечитывается глазами, разделение раундов полезно.
- [Окрашенные строки `render_report`/`gate.render` могут попасть не в тот stream] → контрактом
  параметра `stream`: красим для того же stream, в который печатаем; cli и тесты зовут
  согласованно.
- [Кастомные `llm_colors` больше не влияют на строки опций] → зафиксировано сценарием спеки
  «Конфиг не перекрывает меню»; в README — примечание.
- Пересечения с активными changes (`stream-llm-output-live`, `human-readable-request-dump`) —
  общие файлы только `ui.py`/`llm.py`, аспекты независимы; порядок применения любой.

## Migration Plan

Код и тесты в одном apply; миграций данных нет. Откат — revert коммита: вывод возвращается к
прежним строкам меню/отчёта, конфиг не затронут.
