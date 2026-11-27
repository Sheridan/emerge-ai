# Tasks

## 1. ui.py: слоты подсветки решений и шкала типов

- [x] 1.1 Добавить в `ui.py` константы блока решений (`DECISION_BANNER` фиксированной ширины
  ~40, bold-yellow баннер через `PROMPT_SGR`, тело `yellow`, цифры `green`) и помощники
  печати строк блока для переданного stream; проверить тестами `test_ui`: в фейковом TTY
  баннер/блок/цифры с нужными SGR, в pipe и при `NO_COLOR` — тот же текст без escape-кодов.
- [x] 1.2 Добавить `KIND_COLORS` (полосы из design D4) и `kind_sgr(kind)` с пустым результатом
  для неизвестных имён; проверить тестом `test_ui` по всем видам спеки плюс `other`/мусор.
- [x] 1.3 Переработать `ui.render_question`: пустая строка + баннер перед опциями, пустая
  строка после; строки опций — жёлтые, `N.` — зелёные, вопрос сохраняет
  `llm_colors.question`; `choice_prompt`/`echo_answer` не трогать. Проверить тестами
  `test_ui` и обновлёнными ожиданиями `test_agent` (цветной TTY vs plain).

## 2. Меню вариантов: gate и consent

- [x] 2.1 `gate.render(variants, *, stream=sys.stdout)`: баннер и разделители по D2, `[N]` —
  зелёный, остальное тело — жёлтое; проверить тестами `test_gate` (окрашенный фейковый TTY,
  pipe — только текст плюс баннер).
- [x] 2.2 `consent.render_question`/`run_dialog` принимают `stream` и пробрасывают его в
  `gate.render`; `cli.py` передаёт `plan_stream`; проверить тестами `test_consent` и
  `test_cli`: меню содержит баннер, в pipe без кодов, consent-диалог и `gate.gate()`
  печатают согласованный текст.

## 3. Теги типов находок: триаж и дайджест

- [x] 3.1 `triage.render_report(..., stream=sys.stdout)` красит только тег `[{kind}]` по
  `kind_sgr`; `cli.py` передаёт `plan_stream`; проверить тестами `test_triage` (красные/
  жёлтые/циановые теги в фейковом TTY, `other` без цвета, plain-отчёт в pipe) и smoke-тестом
  `test_cli`.
- [x] 3.2 `enrich`: kind-токен строки находки дайджеста окрашивается тем же `kind_sgr`, остальной
  текст строки — как было; проверить тестами `test_enrich` (окрашенный/plain дайджест).

## 4. Документация и интеграция

- [x] 4.1 Обновить `README.md` (фиксированная палитра: блоки решений жёлтые с зелёными
  цифрами, шкала типов; примечание, что `llm_colors` меню не перекрывает) и `LIVE_CHECKS.md`
  (шаги visual-проверки меню и отчёта в TTY и в pipe); проверить вычиткой текста.
- [x] 4.2 Прогнать `pytest` целиком и `openspec validate highlight-decisions-and-findings --strict`;
  убедиться, что тесты проходят и change валиден без warning'ов.

## Workflow follow-up

- После применения и проверки — архивация change (`openspec archive`) с внесением дельты в
  `openspec/specs/console-output/spec.md`.
