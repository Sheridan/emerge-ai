# Tasks

## 1. Указание языка в описании ask_operator

- [x] 1.1 `agent.ask_language_note(language)`: `""` для пустого/`en*`, иначе фраза про
      human-поля (`question`/`label`/`consequences`) с неизменностью JSON-ключей,
      whitelist-`key` и команд; юниты в `test_agent.py` (en/пусто — пусто, ru — фраза).
- [x] 1.2 `tool_specs(interactive=False, language="English")`: при интерактиве и
      заметке — копия `ASK_TOOL_SPEC` с дописанным `description` (константа не мутируется);
      en/non-interactive — payload побайтно прежний; юниты `test_agent.py`.
- [x] 1.3 `propose()` передаёт `self.context.get("language", "English")` в `tool_specs`;
      сквозной scripted-тест: интерактивный разбор с `context["language"]="Russian"`
      доносит фразу до `tools_seen` клиента.

## 2. Документация и live-проверки

- [x] 2.1 README: `language` покрывает и вопросы агента оператору (`ask_operator`);
      машинные поля аргументов не переводятся.
- [x] 2.2 `LIVE_CHECKS.md`: интерактивный разбор при `language: ru` — вопрос и варианты
      по-русски, `key`/команды целы; при `en` — вывод прежний.
- [x] 2.3 `pytest` зелёный (кроме предсуществующих live-провалов);
      `openspec validate localize-llm-questions --strict` зелёный.
