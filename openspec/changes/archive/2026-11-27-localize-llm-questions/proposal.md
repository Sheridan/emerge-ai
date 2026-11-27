# Proposal

## Why

Вопросы агента оператору (`ask_operator`) приходят на английском даже при
`"language": "ru"`: текст вопроса, ярлыки и последствия вариантов модель заполняет в
аргументах tool-call — а они для модели выглядят «машинным JSON», на который общая
директива «Always respond in X» из system-промпта не распространяется. Директивы
структурных ответов (`fix-llm-response-language`) пинят ключи JSON и прямо просят
переводить human-поля — но у канала вопросов такой директивы нет ни в описании инструмента,
ни в интерактивной директиве.

## What Changes

- В описание инструмента `ask_operator` (только интерактивные прогоны) добавляется
  указание: текст `question`, `label` и `consequences` пишется на языке оператора;
  ключи JSON, значения whitelist-`key` и команды остаются как указаны.
- Язык берётся из `context["language"]` (уже резолвнут `resolved_language()`),
  для английского/absence описание не меняется — en-промпты побайтно прежние.
- Вне scope: перевод интерфейсных строк emerge-ai (вопросы и меню самой программы),
  формальные ошибки `validate_question` (обращены к модели, остаются английскими).

## Capabilities

### New Capabilities

<!-- нет -->

### Modified Capabilities

- `config-prompts`: требование «Язык ответов» — директива языка покрывает и human-поля
  tool-call'ов канала вопросов (`ask_operator`), машинные поля аргументов не переводятся.

## Impact

- `src/emerge_ai/agent.py` — `ask_language_note()`, `tool_specs(interactive, language)`,
  передача `context["language"]` в `propose`.
- Тесты `test_agent.py` (описание инструмента при ru/en, сквозной scripted-тест через
  `tools_seen`), README (`language`), `LIVE_CHECKS.md`.
