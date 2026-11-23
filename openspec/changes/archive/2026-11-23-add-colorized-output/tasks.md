# Tasks

## 1. Инфраструктура цвета (ui.py)

- [x] 1.1 Создать `src/emerge_ai/ui.py`: SGR-константы, `supports_color(stream)` (isatty + `NO_COLOR` + `TERM != dumb`, проверка per-call), `paint(stream, sgr, text)`, `strip_ansi(text)`; тесты в `tests/test_ui.py` на комбинации tty/NO_COLOR/TERM и отсутствие кодов в не-tty
- [x] 1.2 В `ui.py`: whitelist имён цветов (16 базовых + `dim`/`bold` + `off`/null) с маппингом в SGR и разрешение палитры `llm_colors` с дефолтами и warn на невалидное имя; тесты: валидное имя → код, невалидное → дефолт + warn-строка, `off` → plain

## 2. Гигиена входа в LLM

- [x] 2.1 `runner.run_emerge_capturing`: писать в stdout сырые строки, в буфер класть `strip_ansi(line)`; тест: вывод побайтово равен исходному (с ANSI), возвращённый буфер без ESC
- [x] 2.2 Стрип ANSI в `sandbox.journal_search` и `sandbox.pretend_emerge` (единственный потребитель — LLM); тесты sandbox на ANSI-содержащем фикстурном выводе
- [x] 2.3 Регрессия digest: тест `post_run_digest` на крашеном выводе с `[ebuild`-строками перечисляет пакеты, а не «ничего»; убедиться, что `incident.stderr_tail` без ESC (тест в test_incident)

## 3. Фиксированная палитра собственных сообщений

- [x] 3.1 Хелперы `ui.err/warn/ok/info` (префикс `emerge-ai: `) и перевод всех ad-hoc статусных print в `cli.py` на них; тесты: capsys → plain без ESC, monkeypatch-isatty → красные коды в ошибке
- [x] 3.2 Градиент tier в `enrich.plan_digest` и `doctor.doctor_report`, окраска `+`/`-` в `etcupdate.show_diff`, bold/yellow для confirm-промпта и override-вопроса; тесты: capsys plain, isatty → ожидаемые коды в строках tier 1 и diff-строк

## 4. Конфиг `llm_colors`

- [x] 4.1 `llm_colors` в `Config.DEFAULTS`/`from_dict` (вложенный dict content/reasoning/question), валидация через существующий warn-механизм; тесты `test_config.py`: отсутствие ключа → дефолты, частичный dict, невалидное имя → warn + дефолт этого поля, unknown key не затронут

## 5. Рендерер LLM-блоков

- [x] 5.1 `ui.paint_llm_block(text, palette, stream)`: построчно, префикс `QUESTION:` → question-цвет, остальное → content-цвет; unit-тесты с monkeypatch-isatty и на `off`/plain
- [x] 5.2 Подключить рендерер в трёх точках: `LLMClient.render` (content + reasoning палитрой вместо безусловного dim), печать proposal в `cli._maybe_agent`, печать digest в `cli._changelog_mode`; тесты: fake-LLM с `QUESTION:`-строкой в TTY даёт два цвета в stderr, capsys даёт plain, `-v`-сценарии config-prompts не сломаны

## 6. Промпт-директивы

- [x] 6.1 PLAIN-text-директива (без markdown) в системный промпт агента (`agent.propose`) и в `CHANGE_SYSTEM`; конвенция `QUESTION:` в промпт агента; тесты в `test_agent.py`/`test_prompts.py` на сборку промпта

## 7. Интеграция

- [x] 7.1 Полный `pytest` зелёный; прогон greps: ни один capsys-фикстурный вывод e2e-тестов не содержит ESC-кодов; обновить README (NO_COLOR/isatty-политика, `llm_colors`, маркер `QUESTION:`) и сверить с разделом конфигурации

## Workflow follow-up

- Синк/архив изменения после ревью по правилам проекта.
