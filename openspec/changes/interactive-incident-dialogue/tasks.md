# Tasks

## 1. Рендер опроса в ui

- [x] 1.1 Добавить `ui.render_question(question, options, palette, stream)`: вопрос — question-цвет палитры, пронумерованные варианты `label — consequences` — content-цвет, plain при не-TTY/`NO_COLOR`/`TERM=dumb` (правила `console-output`); тесты в `tests/test_ui.py` на крашеный TTY-вывод, plain pipe и пустые опции
- [x] 1.2 Добавить форматирование строки ввода выбора (`[1..n], [c] свой текст, [q] выйти: `) стилем `ui.prompt` и эхо-печать принятого ответа; тест: в TTY строка ввода выделена, эхо выбранного варианта попадает в поток, в pipe — plain

## 2. Инструмент ask_operator и режимный промпт в агенте

- [x] 2.1 Добавить tool-spec `ask_operator` (question, options[{label, consequences}]) и условную сборку tool-листа: инструмент включается только при `interactive=True` (параметр `propose()`); тест: `ScriptedClient` видит `ask_operator` в payload при interactive и не видит без него
- [x] 2.2 Реализовать dispatch-обработку: валидация схемы (1–6 вариантов, непустые поля; ошибка — без списания бюджета), per-round guard (второй вызов в ходе модели → `{"error": "one question at a time"}`), бюджет ≤3 показанных вопросов, флаг «опрос закрыт» (после quit/EOF — молчаливый `{"status":"no-answer"}`); ответы и вызовы в `result.trace`; unit-тесты на все ветки с scripted ask-каналом
- [x] 2.3 Канал ввода как seam: `IncidentAgent(..., ask_channel=None)`, дефолт — `ui.render_question` в stderr + `input()`, `EOFError` → quit; scripted-канал в тестах: выбор номера → `{"status":"answered","choice":...}`, нераспознанный ввод → `free_text` дословно, `q`/EOF → закрытие опроса без зависания
- [x] 2.4 Режимные директивы системного промпта в `propose()`: убрать «never wait for the answer» и `QUESTION:`-директиву; в интерактиве — «вопрос только через ask_operator, варианты предварительно проверены pretend_emerge и содержат последствия»; в не-интерактиве — «вопросов нет; заверши proposal секцией `ASSUMPTIONS:`»; обновить ассерты `tests/test_agent.py` (нет маркерной директивы, есть режимная, есть `ASSUMPTIONS:` в неинтерактивном промпте)

## 3. Проброс интерактивности из CLI

- [x] 3.1 В `cli.main` вычислить `interactive = not pretend and not mode.noninteractive and sys.stdin.isatty()` и передать в `_maybe_agent` (новый именованный параметр с обратимым дефолтом) и далее в `IncidentAgent.propose` во всех трёх ветках сбоя (merge-fail без `-a`, plan-failed, merge-fail после `-a`); тесты в `tests/test_cli.py`: fake `agent_fn` фиксирует `interactive=False` при `-p`, при `--noninteractive` и при не-TTY stdin; `interactive=True` при monkeypatch-isatty без `-p`
- [x] 3.2 Дефолтный `IncidentAgent`-путь `_maybe_agent` принимает interactive и не ломает существующий seam `agent_fn(incident)` (обратная совместимость сигнатуры); тест: вызов со старым одноаргументным `agent_fn` проходит как раньше, `plan-failed` с `-p` по-прежнему выходит сразу после proposal (ни одного чтения stdin — проверить monkeypatch `input`, бросающим AssertionError)

## 4. Интеграция и живой прогон

- [x] 4.1 e2e-тест на stub-emerge с падающим планом: interactive=True (scripted-ask-канал, monkeypatch isatty) — вопрос показан, выбор «2» дошёл до финального proposal; interactive=False — stdin не читается, proposal содержит `ASSUMPTIONS:`; проверить в `tests/test_cli_integration.py`/`test_replay_e2e.py` паттерном существующих тестов
- [ ] 4.2 Integration-тест (маркер `integration`) на живом strata-эндпоинте: scripted-ответ на `ask_operator`, модель обязана вызвать инструмент с валидной схемой и встроить ответ в proposal; при отказе модели — лимиты (guard/бюджет) завершают разбор штатно; допуск один retry, как в существующих live-реплеях
- [ ] 4.3 Прогон полного тестового набора (`pytest`, без `integration`) зелёный; живой ручной сценарий «`emerge-ai -uDN @world` на реальной поломке world, ответить на один вопрос» задокументировать в `LIVE_CHECKS.md`
