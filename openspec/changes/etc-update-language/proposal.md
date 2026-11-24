# Proposal

## Why

Требование «Язык обоснований» (spec `etc-update-llm`) распространяется и на разбор
конфиг-файлов, но директива языка есть только в prompt главного агента
(`assemble_system_prompt` дописывает `Always respond in {language}`, `src/emerge_ai/prompts.py:81-94`,
значение из `cfg.resolved_language()`). Промпт LLM-сверки конфигов целиком англоязычный:
константа `ETC_SYSTEM` (`src/emerge_ai/etcupdate.py:66-67`) и `build_merge_prompt`
(`:69-89`) не содержат ни слова о языке, и CLI (`src/emerge_ai/cli.py:180`) язык туда не
передаёт. Результат (REVIEW_NOTES M12): при `language: ru` обоснования решений по конфигам
приходят по-английски, вопреки обещанию README (`:154` «Язык ответов — из конфигурации»).

## What Changes

- Язык ответов (`cfg.resolved_language()`) передаётся во всю цепочку LLM-разбора конфигов:
  system-часть (`ETC_SYSTEM` становится функцией с директивой языка) и prompt слияния.
- Директива явно разделяет: человекочитаемое обоснование — на выбранном языке, а машинная
  часть решения (JSON-ключи, значения `action`) — без изменений, чтобы парсер не ломался.
- Поддерживаются и зафиксированный `language` (`ru`, `de`, …), и `auto` (резолв по локали),
  как у главного агента; отдельного языка для etc-разбора не вводится.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `etc-update-llm`: требование «Язык обоснований» уточняется: директива языка обязана
  присутствовать в prompt разбора конфиг-файлов; добавлены сценарии для `language: de`
  (пример из брифа) и `auto`-резолва по локали.

## Impact

- **Код**: `src/emerge_ai/etcupdate.py` (`ETC_SYSTEM`→`etc_system(language)`,
  `build_merge_prompt`, `llm_decide` — новый параметр языка), `src/emerge_ai/cli.py:180`
  (передача `cfg.resolved_language()`).
- **Тесты**: `tests/test_etcupdate.py` (промпт-тесты на директиву, обновление сигнатур,
  сквозной test-double `language: de` через `_etc_flow` — тесты `_etc_flow` живут там же).
- **Docs**: README `:154` — утверждение про язык становится фактом; сверить.
- **Смежные changes**: `fix-etc-web-fetch-stub` трогает соседние строки `_etc_flow`
  (веб-фаза), пересечение только по месту вызова — конфликтов по смыслу нет.
