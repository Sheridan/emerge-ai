# Tasks

Зависит от `fix-package-edit-directory-target`: опирается на его
`resolve_package_target`/`destination_label`/`package_files` и применяется после
него. Видов-продюсеров правки лицензий нет, поэтому ни один существующий
сценарий не меняет вывод — изменения закрепляются юнитами канала.

## 1. Имя канала из одной таблицы

- [x] 1.1 В `config_edit` — `CHANNEL_FILE = {"accept_license": "package.license"}`
      и `channel_file(kind) -> str` (иначе `package.<kind>`); `resolve_package_target`
      и `destination_label` берут имя из неё. Проверка юнитом
      `tests/test_config_edit.py`: `channel_file("accept_license") ==
      "package.license"`, остальные виды из `KINDS` → `package.<kind>`;
      `resolve_package_target("accept_license", "=app-misc/foo-1.0 *ALL",
      etc_dir=tmp)` == `tmp/package.license`.
- [x] 1.2 Запись идёт в это имя: `apply_package_edit` (он пишет в результат
      разрешения) и анонс активности `editing <path>: + <line>`. Проверка
      юнитом: после правки лицензий на tmp-корне существует `package.license`
      со строкой и аудит-маркером, `package.accept_license` не создан;
      существующие тесты других видов зелёны без правок ожиданий.
- [x] 1.3 Инвариант имени вместо дрейфа (D4): в `tests/test_config_edit.py`
      — ожидаемое отображение всех видов `KINDS` зафиксировано буквально и
      множество имён ⊆ закрытого перечня читаемых portage имён; существующий
      `test_undo_text_exists_for_every_edit_kind` переведён на `channel_file`.
      Проверка: правка таблицы без обновления перечня роняет этот тест
      (локально убедиться временной правкой и откатить).

## 2. Отмена, обзор и формулировки по тому же имени

- [x] 2.1 `UNDO_TABLE` и `undo_text` строятся из `channel_file`. Проверка
      юнитами: `undo_text("accept_license")` оканчивается на `package.license`;
      `undo_text("accept_license", line="app-misc/foo *NEEDED", etc_dir=каталог)`
      называет `package.license/app-misc`; формулировки остальных видов не
      изменились.
- [x] 2.2 `package_files(kind="accept_license")` обходит `package.license`
      (файл и каталог с файлами категорий), `kind=None` — прежний шаблон
      `package.*`. Проверка юнитами: `get_package_edit_lines("accept_license")`
      возвращает строки `package.license` и файлов внутри него с верной
      пометкой «аудит/не аудит», `remove_by_run` удаляет строку прогона из
      `package.license/dev-libs`, оставляя строку пользователя и сам файл,
      повторный вызов → `[]`;
      `test_package_files_stays_inside_the_package_prefix` зелёный без правок.
- [x] 2.3 Сообщение о пропущенном дубле в `cli._apply_action` печатает имя
      канала из той же таблицы (D5). Проверка интеграционным тестом в
      `tests/test_cli_integration.py`: строка лицензий уже есть в
      `package.license` → в stderr `package.license: '…' already present —
      skipped`, файл не изменён, `package.accept_license` не создан.

## 3. Каталог лицензий, документация, финальная проверка

- [x] 3.1 Раскладка применяется к новому имени без исключений (D3). Проверка
      юнитами: tmp-корень с каталогом `package.license` → запись в
      `package.license/<category>` (`destination_label` даёт
      `package.license/<category>`), строка без категории →
      `package.license/aimerge`, подкаталог вместо файла категории →
      `ChannelError` с этим путём.
- [x] 3.2 Docs: README (раздел про канал правки `package.*`) — имя файла
      лицензий как исключение из «имя вида = имя файла»; в
      `prompts/rules/20-ladder.md` у уровня 1 назван `package.license`, чтобы
      совет модели не ссылался на нечитаемый файл. Проверка: текст прочитан,
      `grep -rn "package.accept_license" src prompts README.md` не оставляет
      утверждений, что канал пишет в него.
- [x] 3.3 Запись в `LIVE_CHECKS.md`: ручная проверка на живом хосте — правка
      лицензий создала/дополнила `/etc/portage/package.license` с аудит-
      маркером, `test ! -e /etc/portage/package.accept_license`, перезапущенный
      emerge не сообщает о непринимаемой лицензии, отмена по маркеру чистит
      только строку прогона.
- [x] 3.4 Финальная проверка: `.venv/bin/python -m pytest -q -m "not
      integration"` зелёный; `.venv/bin/ruff check src tests` и `mypy src` без
      новых замечаний относительно `HEAD`;
      `openspec validate "fix-license-channel-filename" --strict` проходит.

## Workflow follow-up

- Применять после `fix-package-edit-directory-target`; архивировать дельты
  `repair-actions` в том же порядке.
- Живая проверка из 3.3 — за пользователем (правки в `/etc/portage` на хосте).
