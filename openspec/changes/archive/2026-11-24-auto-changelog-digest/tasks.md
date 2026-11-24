# Tasks

## 1. Конфиг

- [x] 1.1 `config.py`: `DEFAULTS["changelog_digest"] = False` (рядом с `post_run_digest`, `config.py:15-27`) + поле `Config.changelog_digest: bool = False`
      (реальность: ключ внесён ранее `align-config-schema` с default true — здесь резолв в false по сценарию спека «не настроено → тихо»)
- [x] 1.2 Тест загрузки: ключ принимается без «ignoring unknown key», отсутствие ключа → false

## 2. Хук после прогона и контекст LLM

- [x] 2.1 `_post_run_digest` (`cli.py:229-236`): после существующего дайджеста — при `cfg.changelog_digest` и непустом перечне собранных пакетов построить `changelog.collect_digest(..., packages=[cpv...])`; клиент при `cfg.endpoint` (паттерн `_changelog_mode`, `cli.py:238-250`)
- [x] 2.2 Печать результата `ui.paint_llm_block`/plain в stderr (последовательно с `post_run_digest`), присвоить `run.changelog = ui.strip_ansi(text)`; весь шаг под `try/except Exception` → warn в stderr, код возврата не трогаем (design D2)
- [x] 2.3 `state.RunState`: поле `changelog: str | None = None` (`state.py:41-51`); убедиться, что `save_run` после `_post_run_digest` (`cli.py:323`, `cli.py:424`) пишет его, `load_run` старых отчётов даёт `None`
- [x] 2.4 `collect_digest(..., packages: list[str] = ())` (`changelog.py:111-151`) → проброс в `llm_digest` (`changelog.py:98-108`): строка «merged in this run: …» в user-части; пустой `packages` — промпт и вывод побайтно прежние (ручной `--changelog` не меняется)

## 3. Тесты

- [x] 3.1 `tests/test_cli_integration.py`: опция off → `collect_digest` не вызван, вывода нет; on + rc==0 (fake client/источники) → дайджест напечатан и `run.changelog` в отчёте; rc!=0 → не вызван
- [x] 3.2 Исключение внутри шага → код возврата прогона прежний, warn в stderr; без endpoint → сырой перечень (`client=None`)
- [x] 3.3 Тест `llm_digest` с `packages` — строка прогона в промпте; regression: вызов без `packages` идентичен старому

## 4. Документы

- [x] 4.1 README: описание `changelog_digest` (default off) и связи с `--changelog`; `REVIEW_NOTES.md` M11 закрыт
- [x] 4.2 `LIVE_CHECKS.md`: чек выключенной опции (пустой вывод/тишина) и включённой с фейковым endpoint; полный `pytest` зелёный
