# Tasks

## 1. Резолв и директива языка

- [ ] 1.1 `Config.resolved_language()`: срез региона/кодировки (`ru_RU.UTF-8` → `ru`),
      таблица кодов → полные названия (ru/en/uk/de/fr/es + Common), неизвестное — как есть,
      `auto` — из локали через ту же нормализацию, фолбэк English; юниты `test_config.py`
      (`"ru"` → `Russian`, `auto`+LANG=ru_RU.UTF-8 → `Russian`, `xx` → `xx`, `en` → `English`).
- [ ] 1.2 `prompts.language_directive(language, structured=False)` — общая директива +
      структурный вариант с хвостом про неизменность JSON-ключей;
      `assemble_system_prompt` использует хелпер; юниты `test_prompts.py` (обычный и
      структурный вид, отсутствие двойной директивы).

## 2. Проводка в LLM-вызовы

- [ ] 2.1 `_maybe_agent`: `collect_context(info, cfg.resolved_language())` вместо сырого
      `cfg.language`; тест `test_cli.py`: system-промпт содержит «respond in Russian» при
      `"language": "ru"`.
- [ ] 2.2 Параметр `language` в `enrich.build_plan_summary_messages` (структурный вариант) и
      `consent.build_analysis_messages` (структурный вариант); проводка
      `language=cfg.resolved_language()` из `cli`; юниты `test_digest.py`/`test_consent.py`
      (директива в system-промпте; парсеры принимают human-поле на русском, ключи целы).
- [ ] 2.3 Параметр `language` в `changelog.llm_digest`/`collect_digest` + проводка из `cli`
      (обычный и `--changelog` режимы); юнит `test_changelog.py` (директива в промпте);
      интеграционный тест `test_cli.py` — changelog-дайджест вызывается с резолвнутым
      языком.
- [ ] 2.4 Прогон `pytest` зелёный; регрессии «нет endpoint / сбой LLM» (поведение без
      изменений) проверены существующими тестами `test_cli.py`.

## 3. Документация и live-проверки

- [ ] 3.1 README: уточнить `language` — нормализация кодов (`ru` → Russian), покрытие всех
      LLM-выводов (агент, сводка, news, consent, etc-update, changelog), JSON-ключи не
      переводятся; вычитка глазами.
- [ ] 3.2 `LIVE_CHECKS.md`: ручная проверка `"language": "ru"` — сводка дайджеста и proposal
      агента по-русски, JSON-поля etc-update/consent не двигаются; `language: en` — вывод
      на английском.
- [ ] 3.3 `openspec validate fix-llm-response-language --strict` зелёный; сценарии дельты
      config-prompts покрыты тестами групп 1–2.
