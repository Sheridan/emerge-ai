# Tasks

## 1. Промпт с директивой языка

- [x] 1.1 В `src/emerge_ai/etcupdate.py` заменить константу `ETC_SYSTEM` (`:66-72`) на
      `etc_system(language)` с директивой: человекочитаемое (`reason`, пояснения) — на
      `{language}`, JSON-ключи и коды `action` — без изменений
- [x] 1.2 `build_merge_prompt(new_text, current_text, docs, language)` — обязательный
      параметр `language`, system-сообщение из `etc_system(language)` (`:75-89`)
- [x] 1.3 `llm_decide(client, new_path, current_path, docs, language)` — проброс языка в
      `build_merge_prompt` (`:106`)

## 2. Проброс из CLI

- [x] 2.1 В `_etc_flow` (`src/emerge_ai/cli.py:180`) передавать `cfg.resolved_language()` в
      `llm_decide`

## 3. Тесты

- [x] 3.1 `tests/test_etcupdate.py:14` — обновить вызов под новый сигнатурный контракт;
      добавить тест: `language="de"` → system-сообщение содержит директиву `respond in de`,
      `language="russian"` → `respond in russian`
- [x] 3.2 `tests/test_etcupdate.py:178` — обновить `llm_decide`; тест с fake-клиентом:
      ответ на немецком с валидным JSON парсится `parse_decision` без изменений
- [x] 3.3 `tests/test_etcupdate.py`: в конфиг-фикстуре (`:117`) `"language": "de"`,
      fake-клиент перехватывает messages → в system-роли директива `de`, решение обработано
- [x] 3.4 Прогнать `pytest` целиком, все тесты зелёные

## 4. Docs

- [x] 4.1 Сверить README (`:154` «Язык ответов — из конфигурации») — утверждение теперь
      верно для etc-разбора; при расхождении уточнить
- [x] 4.2 `openspec validate etc-update-language` проходит без ошибок
