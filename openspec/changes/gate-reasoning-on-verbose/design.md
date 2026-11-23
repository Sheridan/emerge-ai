# Design

## Context

`reasoning_show` (config.py:17,37) читается единственным местом — `LLMClient.render` (llm.py:91-96), который печатает `[reasoning] ...` и content. В проде `render` вызывается только из `run_tool_loop(render_to=...)`, а единственного production-пользователя цикла (`agent.py:226`, консультация при инциденте) вызывают **без** `render_to` — т.е. сегодня опция фактически ни на что не влияет. CLI-детекция emerge-флагов уже есть: `runner.flag_present` cluster-aware (по ней работают `pretend`/`ask`, cli.py:245-246). Мест создания `LLMClient`: cli.py:54 (tiers), :99 (agent), :182 (changelog), plus `_etc_flow` через `client_factory` (cli.py:132-133,147).

## Goals / Non-Goals

**Goals:**
- Единственный переключатель вывода рассуждений — `-v`/`--verbose` emerge (cluster-aware), default — выключен.
- Опция `reasoning_show` полностью удалена из кода, конфига, спеки, документации; старый ключ в конфиге даёт целенаправленное deprecation-предупреждение.
- Фичу сделать наблюдаемой: при `-v` консультация агента при инциденте стримит reasoning в stderr.

**Non-Goals:**
- Не привязывать к `-v` остальные digestive/doctor-выводы (scope creep).
- Не менять `tiers`/`changelog`/`etcupdate` path (они зовут `.chat` без render) — reasoning там не печатается и дальше.
- Не вырезать `-v` из argv (emerge сам решит, что с ним делать).

## Decisions

### D1. Явный `show_reasoning` на клиенте вместо глобального состояния
`LLMClient.__init__(..., *, show_reasoning: bool = False)`, `render` использует `self.show_reasoning`. CLI вычисляет `verbose = flag_present(emerge_args, ("-v", "--verbose"))` рядом с `pretend`/`ask` (cli.py:245) и пробрасывает в `_make_tier_service`, `_maybe_agent`, `_changelog_mode`, `_etc_flow` (в ней `client_factory(cfg, show_reasoning=verbose)`).
Альтернативы: (a) параметр `render(resp, show=...)` — переносит заботу о CLI-контексте в `run_tool_loop` и каждого caller'а; (b) module-level флаг — скрытая зависимость, ломаемая тестами и повторными вызовами `main()` в одном процессе (интеграционные тесты именно так и делают).

### D2. Стрим агента при `-v` = `render_to=sys.stderr`
`IncidentAgent.propose(..., render_to=None)` прокидывает в `run_tool_loop`; `_maybe_agent` передаёт `sys.stderr` при verbose. Побочный эффект: финальный content напечатается и из render_to, и summary-строкой `agent proposal:` — принято для verbose-режима (сырой поток + итог). Иначе фича остаётся мёртвым кодом (см. Context).
Альтернатива: отдельный print только reasoning внутри цикла — дублирует логику render в двух местах.

### D3. Deprecation-предупреждение удалённого ключа
`config.py`: таблица `_REMOVED_KEYS = {"reasoning_show": "управляется emerge-флагом -v/--verbose"}`; `from_dict` для таких ключов печатает адресное сообщение и исключает их из общего «ignoring unknown key». Альтернатива — только общий warning: пользователь не узнает, чем заменить.

### D4. Тесты вместо `Config(reasoning_show=...)`
`tests/test_llm.py` (unit + live `_live_client`), `tests/test_config.py` (дефолт, удалённый ключ) и новые CLI-тесты (`-av` → emerge-stub получает `-av`, reasoning-строка в stderr при стабовом эндпоинте) переводятся на `show_reasoning=`/argv. Характеризующий тест «без `-v` reasoning не виден» — общий сценарий спеки.

## Risks / Trade-offs

- [Меняемое поведение по умолчанию: конфиг `reasoning_show: true` больше не показывает reasoning без `-v`] → осознанное (запрос), README + deprecation-warning при загрузки такого конфига.
- [При `-v` proposal агента виден дважды] → принятый trade-off verbose-режима (D2); итоговая строка — источник истины для скриптов.
- [reasoning-поток не попадает в захват `run_emerge_capturing`] → это stderr emerge-ai, не вывод emerge; в run-state не пишется (как и весь diagnostic-вывод).
- [Пересечение с `refactor-cli-flag-parsing` в `cli.py`] → changes ортогональны (own-flags vs emerge-flags); применять последовательно, после каждого — полный `pytest`; merge-конфликт тривиален.

## Migration Plan

Миграции данных нет: ключ в конфиге становится no-op с подсказкой; откат — revert change (опция вернётся). README и дефолтный конфиг-шаблон (`packaging/emerge-ai.json.default`) ключа не содержат — проверено.

## Open Questions

(нет)
