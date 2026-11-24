# Tasks

## 1. LLM-seam в enrich

- [ ] 1.1 `plan_digest` (`enrich.py:47-72`): необязательный параметр `summarize: Callable[[str], str] | None`; порядок — собрать детерминированные строки, затем (если `summarize`) вызвать его, результат дописать через `ui.paint_llm_block`/ANSI-stripped
- [ ] 1.2 Промпт сводки: системная часть — 2–5 строк plain text (опора на `prompts.PLAIN_TEXT_DIRECTIVE`), запрет выдумывать числа и утверждать отсутствующее во входе; вход — текст ядра + JSON `[{cpv, tier}]` через `injection.wrap_untrusted`
- [ ] 1.3 Локальный except вокруг `summarize`: любое исключение → `None` (без warn), ядро возвращается как раньше (design D3)

## 2. Подключение в cli

- [ ] 2.1 План-фаза (`cli.py:346-352`): при `cfg.endpoint` конструировать `LLMClient` (паттерн `_changelog_mode`, `cli.py:238-250`) и передавать в `plan_digest` замыкание-колбэк; без endpoint — `summarize=None`
- [ ] 2.2 Убедиться, что внешний except (`cli.py:356-357`) не вызывается штатным отказом LLM, и прочие сбои обогащения по-прежнему сводятся к warn

## 3. Тесты

- [ ] 3.1 `tests/test_enrich.py`: фейковый `summarize` → сводка идёт после строк ядра, ядро байт-в-байт прежнее; `summarize` бросает → текст идентичен сегодняшнему
- [ ] 3.2 `tests/test_cli_integration.py`: без endpoint `summarize` не вызывается вовсе (spy); с «endpoint» (fake client) — вызывается один раз за план-фазу
- [ ] 3.3 Тест инъекции: CPV с паттерном вида «ignore previous instructions» попадает в промпт обёрнутым `wrap_untrusted`

## 4. Документы

- [ ] 4.1 `README.md` 66-67: текст остаётся истинным; при необходимости уточнить фразу про деградацию без endpoint; закрыть M4 в `REVIEW_NOTES.md`
- [ ] 4.2 Полный `pytest` зелёный; живой чек в `LIVE_CHECKS.md`: `emerge-ai -p` с активным endpoint показывает LLM-блок, с пустым endpoint — нет
