# Tasks

Независим от остальных открытых change: правит только канал правки
`package.*`. Формулировки consent (D7) опираются на существующий
`consent.menu_specs`; новые white-команды и триаж не трогаются.

## 1. Разрешение цели записи

- [x] 1.1 В `config_edit` — `category_of(atom) -> str | None` (первый токен
      строки через `tiers.package_of`, категория проверяется шаблоном
      `[A-Za-z0-9+._-]+`) и чистая `resolve_package_target(kind, line, *,
      etc_dir)`: каталог → `package.<kind>/<category>`, резерв
      `package.<kind>/aimerge` при отсутствии категории, иначе
      `package.<kind>`. Проверка юнитами в `tests/test_config_edit.py`:
      каталог + `=dev-libs/jemalloc-5.4.0-r2 ~amd64` → `…/dev-libs`;
      `package.use`-файл → append в файл, каталог не создан; цели нет → создан
      файл, не каталог; `*/* cuda` и `@world` → `…/aimerge`.
- [x] 1.2 `apply_package_edit` пишет в результат разрешения и по-прежнему
      идемпотентен по дубль-проверке вызывающего; анонс активности (D1, spec:
      progress-logging) печатает фактический путь. Проверка: расширенный
      `test_writes_are_announced` для каталожной раскладки даёт
      `editing <etc>/package.accept_keywords/dev-libs: + =dev-libs/…`;
      существующие тесты файловой раскладки (`test_apply_package_edit_*`,
      `test_write_stays_inside_etc_dir`) зелёны без правок ожиданий.
- [x] 1.3 Недоступная цель — `config_edit.ChannelError(path, reason)`: цель
      внутри каталога существует, но не обычный файл (подкаталог с именем
      категории), либо append дал `OSError`. Проверка юнитом: подкаталог
      `package.mask/dev-libs` → `ChannelError`, ни один файл каталога не
      изменён, `IsADirectoryError` наружу не выходит.

## 2. Отмена и обзор по каталогу

- [x] 2.1 Общая генерация целей `package.*` (файлы + рекурсивно файлы внутри
      каталогов), через неё — `remove_by_run` и `get_package_edit_lines`
      (D6). Проверка юнитами: строка удалена по маркеру этого прогона из
      `package.accept_keywords/dev-libs`, строка пользователя в том же файле
      цела, файл остался (опустевший не удалён), повторный
      вызов → `[]`; обзор каталога `package.use` показывает строки всех его
      файлов с верной пометкой «аудит/не аудит».
- [x] 2.2 Убедиться, что разрешение цели живёт только в `config_edit`:
      `grep -rn 'package\.' src/aimerge | grep -v config_edit.py` не оставляет
      мест, где путь `package.<kind>` строится в обход разрешения (рекурсивная
      дубль-проверка в `cli._apply_action` — исключение, она уже обходит
      дерево). Результат — либо найденное место переведено на разрешение, либо
      в коде зафиксировано, почему исключение законно.

## 3. Отказ канала вместо падения прогона

- [x] 3.1 `cli._apply_action` (род `package-edit`) перехватывает
      `ChannelError`/`OSError`: печатает `ui.err` с путём и причиной и возвращает
      `{"status": "rejected", "reason": …}` — контракт TOCTOU-отказа
      (whitelist-repair-commands D2). Проверка интеграционным тестом:
      `etc_dir` с каталогом `package.accept_keywords`, куда запись невозможна
      (chmod), → прогон не падает (никакого traceback в выводе), файл не
      изменён, в stderr путь и причина.
- [x] 3.2 Последствия отказа: `_consent_execute` не добавляет вариант в
      `run.consent_repairs` при `rejected`; `_incident_flow.bound()` засчитывает
      такой цикл в `run.repair`, чтобы `REPAIR_LIMIT` ограничивал повтор (D5).
      Проверка тестами: в неинтерактиве повторяющийся отказ не выводится за
      пределы лимита починок и завершает прогон штатным ненулевым кодом с
      подсказкой; интерактивный прогон с тем же отказом показывает меню снова и
      выходит по `q` без изменений системы.

## 4. Показ цели оператору

- [x] 4.1 `undo_text(kind, *, line=None, etc_dir="/etc/portage")` называет
      разрешение из D1 (без `line` — прежняя формулировка, существующий
      `test_undo_text_exists_for_every_edit_kind` зелёный);
      `consent.menu_specs(..., etc_dir="/etc/portage")` использует её в
      detail-строках `edit:`/`undo:`. Проверка юнитами `tests/test_consent.py`:
      на tmp-корне с каталогом формулировка содержит
      `package.accept_keywords/dev-libs`, на файловой раскладке —
      `package.accept_keywords`.
- [x] 4.2 `cli` пробрасывает свой `etc_dir` во все вызовы `menu_specs`
      (диалог мутационного пути). Проверка: `test_cli_integration` с
      `etc_dir=tmp_path/"etc"`, где `package.accept_keywords` — каталог,
      показывает в выводе диалога путь категории (строка `edit: …`), а не
      только вид правки.

## 5. Сквозная проверка и документация

- [x] 5.1 `tests/test_cli_integration.py`: каталожная раскладка end-to-end —
      stub-emerge деградирует, пока нет `etc/package.accept_keywords/dev-libs`,
      выбранный вариант дописывает строку туда, re-resolve даёт
      «plan is clean now», merge без pretend исполняется; параллельно —
      регресс на файловой раскладке (существующий
      `test_consent_degraded_repair_reresolve_then_merge` зелёный без правок
      ожиданий).
- [x] 5.2 Docs: README (раздел про apply-канал и правки `/etc/portage`) —
      правило «каталог → файл категории, резерв `aimerge`, отмена по
      аудит-маркеру обходит каталоги»; запись в `LIVE_CHECKS.md` для ручной
      проверки на хосте с каталожной раскладкой: прогон с masked-находкой
      дописал `package.accept_keywords/<cat>`, файл `package.accept_keywords`
      не появился, строка помечена `# aimerge:`, отмена по маркеру чистит
      только её.
- [x] 5.3 Финальная проверка: `.venv/bin/python -m pytest -q` (unit, без
      маркера `integration`) зелёный; `ruff check src tests` и `mypy src`
      без новых замечаний.
