# Proposal

## Why

Настройка `"language": "ru"` не работает: `_maybe_agent` (`cli.py`) передаёт в машинный
контекст сырое `cfg.language` — промпт получает «Always respond in ru» вместо нормализованного
названия языка, а `Config.resolved_language()` нормализует только `auto`. Хуже того, промпты
LLM-сводки дайджеста (`enrich.build_plan_summary_messages`), анализа consent-меню
(`consent.CONSENT_ANALYSIS_SYSTEM`) и changelog-дайджеста (`changelog.llm_digest`) вообще не
содержат директивы языка — их вывод на английском при `"language": "ru"` неизбежен, даже когда
агент-разбор всё же догадывается отвечать по-русски.

## What Changes

- `Config.resolved_language()` нормализует значение: срез региона/кодировки
  (`ru_RU.UTF-8` → `ru`), таблица кодов → полные названия (`ru` → Russian, `en` → English,
  …), неизвестное значение передаётся как есть; `auto` проходит ту же нормализацию из
  локали с фолбэком English.
- Общий хелпер `prompts.language_directive(language)` — обязательная директива языка для
  пользовательских промптов и структурный вариант с фиксацией англоязычных JSON-ключей.
- Директива входит во все LLM-вызовы с пользовательским выводом: разбор инцидента (через
  `collect_context`), сводка дайджеста, analysis consent-меню, changelog-дайджест;
  news/etc-update уже получают язык — теперь нормализованный.
- Вне scope: строки активности и дампы (`add-progress-logging`), вывод рассуждений
  (`fix-verbose-thinking-output`); новые ключи конфига не вводятся.

## Capabilities

### New Capabilities

<!-- нет -->

### Modified Capabilities

- `config-prompts`: требование «Язык ответов» — нормализация значений `language` к полному
  названию и обязательное присутствие языковой директивы во всех LLM-вызовах с
  пользовательским выводом; структурные JSON-ответы сохраняют англоязычные ключи/коды.

## Impact

- `src/emerge_ai/config.py` — нормализация `resolved_language()`.
- `src/emerge_ai/prompts.py` — `language_directive()`; `assemble_system_prompt` использует
  её вместо инлайн-строки.
- `src/emerge_ai/cli.py` — `_maybe_agent`: `cfg.resolved_language()` вместо сырого
  `cfg.language`; проводка `language=` в вызовы сводки/consent/changelog.
- `src/emerge_ai/enrich.py`, `consent.py`, `changelog.py` — параметр `language` в
  билдерах промптов (структурные — с фиксацией ключей).
- Тесты (`test_config`, `test_prompts`, `test_digest`, `test_consent`, `test_changelog`,
  `test_cli`), README (уточнение `language`), `LIVE_CHECKS.md` (ручная проверка языка).
