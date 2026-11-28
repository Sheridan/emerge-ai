# Tasks

Атом deselect резолвится один раз в `triage.candidates` (D1) — от него зависят
меню (`consent.menu_specs`), ask-канал (`agent._finding_variants`) и ключи
вариантов, поэтому группа 1 идёт первой, иначе её правку пришлось бы
«доисправлять» тестами групп 2–3.

## 1. Атом из world-файла (triage)

- [x] 1.1 В `triage` — `world_entries(world, atom_or_cpv) -> list[str]`: строки
      world с тем же `cat/pkg` (через существующий `_cat_pkg`), порядок файла,
      дубликаты схлопнуты; `world is None` → `[]`. Проверка юнитом
      `tests/test_triage.py`: при `world = ["sys-devel/gcc", "sys-devel/gcc:14",
      "sys-devel/gcc:15", "app-misc/other"]` вызов с `sys-devel/gcc-14` и с
      `=sys-devel/gcc-14` даёт все три строки в этом порядке; пакета нет в
      world → `[]`; дубль строки в world не удваивает результат.
- [x] 1.2 Ветку `deselect` в `candidates()` (triage.py:268-278) построить по
      `world_entries`: N записей → N исполняемых кандидатов с `atom` = строка
      world дословно (текст `remove <запись> from the world set (emerge
      --deselect <запись>)`); записей нет (или `world=None`) → нынешняя
      неисполняемая пара `deselect`+`world-review` с `f.cpv` без изменений.
      Голый `cat/pkg` вместо слотовых записей не предлагается. Проверка
      юнитами `tests/test_triage.py`: находка по `sys-firmware/edk2-bin-202608_p1`
      при world `["sys-firmware/edk2-bin"]` даёт ровно один кандидат с
      `atom == "sys-firmware/edk2-bin"` и без версии в тексте; при трёх
      записях gcc — три кандидата с разными `atom`/ключевыми словами текста;
      существующие `test_candidates_deselect_executable_for_world_member` и
      кейс «не член world остаётся advice» (tests/test_triage.py:146-161)
      зелёны; `python -m pytest -q tests/test_triage.py` зелёный целиком.

## 2. Валидатор и проверка эффекта (whitelist)

- [x] 2.1 Форма атома: дополнить `ATOM_RE`/`_validate_atom` правилом «версия
      есть — оператор обязателен» (`cat/pkg-1.0` → ошибка `is not a package
      atom`, а `=`, `>=`, `~`, `~>` — принимаются; слот и `::repo` остаются
      допустимыми). Проверка юнитами `tests/test_whitelist.py`:
      `{"atom": "dev-x/y-1.0"}` отвергнут с текстом про не-атом,
      `{"atom": "=dev-x/y-1.0"}` и `{"atom": "~dev-x/y-1.0"}` формы приняты
      (членство — по дословной строке, см. 2.2); правка ожиданий
      tests/test_whitelist.py:44-46 и :67-68, где `dev-x/y-1.0`/
      `dev-x/y-1.0:0::repo` считаются валидными, — намеренная (design Risks).
- [x] 2.2 Членство = дословное совпадение: `_validate_atom` (whitelist.py:86-96)
      вместо совпадения по `cat/pkg` ищет `value` среди `e.strip()` строк
      world; текст ошибки `is not a member of @world` сохранить. Проверка
      юнитами: `{"atom": "dev-x/y"}` при `world=["dev-x/y:14"]` отвергнут
      (не член), при `world=["dev-x/y"]` принят; `{"atom": "sys-devel/gcc:14"}`
      принят при `world=["sys-devel/gcc:14"]` и отвергнут при
      `world=["sys-devel/gcc"]` (раньше проходил по `cat/pkg`);
      `"=cat/pkg-ver"` принят ровно когда такая строка есть в world дословно;
      TOCTOU в `execute` (whitelist.py:203) отвергает вариант, если запись
      переписана (слот дописан) между показом и исполнением — юнит с
      «протухшим» `world`-списком.
- [x] 2.3 Проверка эффекта: у `CommandSpec` поле `verify: str | None = None`,
      у `emerge-deselect` — `"world-entry-removed"`; `execute` после запуска
      перечитывает `world_file` и возвращает `changed: True|False|None`
      (`False` и при ненулевом rc), при `changed is not True` — статус
      `no-effect`, аудит-запись `decision: "command-effect"` с `changed` и
      `returncode`, `echo(ui.err(...))` с точной командой ручного deselect;
      нечитаемый world после исполнения → `changed is None`, тоже `no-effect`.
      Проверка юнитами `tests/test_whitelist.py` с фиктивным `runner` и
      tmp `world_file`: rc 0 + запись осталась → `status == "no-effect"`,
      `changed is False`, в аудите вторая строка `command-effect`; запись
      исчезла (фиктивный runner переписывает tmp-world) → `status ==
      "executed"`, `changed is True`; `emaint-fix-world`/`emaint-check-world`
      поля `changed` не получают; прежние тесты `execute` (аудит до
      исполнения, reject без мутации) зелёны.

## 3. Меню, отмена без эффекта, ask-канал

- [x] 3.1 `consent.menu_specs(..., *, exclude: frozenset = frozenset())` —
      варианты с ключом из `exclude` не попадают ни в `specs`, ни в `manual`;
      deselect-спеки (consent.py:166-176) строят key/title/detail/slots из
      `cand["atom"]` (там же, где и были — проверить, что после 1.2 это
      дословная строка world). Проверка юнитами `tests/test_consent.py`:
      degraded-вердикт по `sys-firmware/edk2-bin-202608_p1` +
      `world=["sys-firmware/edk2-bin"]` → один spec с
      `slots.atom == "sys-firmware/edk2-bin"`, заголовок и `undo:`-строка без
      версии кандидата; `exclude={"deselect-sys-firmware/edk2-bin"}` → spec
      исчез, merge остался; существующие deselect-кейсы
      tests/test_consent.py:152-171 переведены на дословный атом.
- [x] 3.2 `cli`: множество `no_effect` рядом с циклом (`cli.py:1125`),
      `_consent_execute` на `status == "no-effect"` (или `changed is not True`
      у команды с verify) добавляет `spec.key` в `no_effect`, печатает
      `ui.info` с ручной командой и НЕ кладёт вариант в `run.consent_repairs`;
      `menu_specs(...)` в цикле вызывается с `exclude=frozenset(no_effect)`.
      Проверка интеграционным тестом `tests/test_cli_integration.py` на
      tmp-world (`sys-devel/gcc:14`) с фиктивным emerge, который при
      `--deselect` файл не меняет: argv содержит `--deselect
      sys-devel/gcc:14` (без версии кандидата), после «исполнения» меню
      пересобирается без этого варианта, в stderr — строка про ручную команду,
      `run.consent_repairs` пуст.
- [x] 3.3 Слот-атом в ask-канале: `agent._finding_variants`
      (agent.py:376-382) после 1.2 сам получает дословные атомы и N ключей
      `deselect-<запись>` — убедиться юнитом `tests/test_agent.py`, что при
      нескольких записях пакета варианты различаются ключом/атомом и совпадают
      с `consent.menu_specs` на тех же данных (существующий кейс
      tests/test_agent.py:743-757 переведён на ожидания «атом = строка
      world»).

## 4. Docs и финальная проверка

- [x] 4.1 Docs: README:229 — слот `emerge --deselect` = дословная строка
      world-файла (не CPV), эффект проверяется по world; рядом (README:159)
      сформулировать deselect как «снимает одну запись world». Запись в
      `LIVE_CHECKS.md`: ручная проверка на живом хосте — вариант меню для
      пакета из world называет запись без версии кандидата, `emerge --deselect
      <запись>` снимает ровно её, «no matching atoms» больше не выглядит
      починкой (сообщение + вариант не повторяется). Проверка: тексты
      прочитаны, `grep -n "deselect" README.md` не остаётся с формулировкой
      «атом из находки».
- [x] 4.2 Финальная проверка: `.venv/bin/python -m pytest -q -m "not
      integration"` зелёный; `.venv/bin/ruff check src tests` и `mypy src` без
      новых замечаний относительно `HEAD`;
      `openspec validate "fix-deselect-world-atom" --strict` проходит.

## Workflow follow-up

- Архивировать дельту `repair-actions` после ревью; в архивной сводке
  зафиксировать, что тесты 2.1/2.2 изменили закреплявшие дефект ожидания.
- Живая проверка из 4.1 — за пользователем (реальный `--deselect` меняет
  `/var/lib/portage/world`).
- Открытые вопросы design.md (`@set`-записи `world_sets`, симметрия в
  ask-канале при `REPAIR_LIMIT = 2`) — вне этого change.
