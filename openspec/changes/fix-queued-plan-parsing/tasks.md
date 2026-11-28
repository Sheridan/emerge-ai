# Tasks

## 1. Разбор pretend-вывода

- [x] 1.1 `digest.py`: `EBUILD_LINE_RE` — любое содержимое статусной скобки
      (`^\[ebuild\s+[^\]]+\]\s+(\S+)`), проверить потребителей (digest, plan)
- [x] 1.2 Фикстуры `tests/test_digest.py` / `tests/test_plan.py`: строки `U ~`, `N *`,
      `R ~` (в т.ч. живая с `USE=...` после CPV) и соседняя `[blocks B ]` — в очередь
      попадают только ebuild-строки

## 2. Честный seam резолвера

- [x] 2.1 `portage_compat`: `parse_emerge_opts(argv)` (через `_emerge.main.parse_opts`,
      перехват SystemExit → `PortageUnavailable`) и `queued_cpvs(graph)`
      (`altlist`, `not installed`, `Package.cpv`)
- [x] 2.2 `plan.build_plan`: argv пользователя через `parse_emerge_opts`, форс
      `--pretend`/`--quiet`, снятие `--ask`; `_iter_installed_tasks` удалён, cpv — из
      `queued_cpvs`; `--nodeps` больше нигде
- [x] 2.3 `tests/test_portage_compat.py` / `tests/test_plan.py`: портаж-подобный fake
      (`cpv`, `installed`; без `.pkg`) — уже установленные в altlist не попадают;
      проверено, что opts резолвера не содержат `--nodeps` и содержат пользовательские
      `-uDN`

## 3. Недоступная очередь видна честно

- [x] 3.1 `consent.menu_specs`: `plan is None` → «queue unknown» в пункте merge; пустой
      план → «0 package(s)»; `tests/test_consent.py` на оба состояния

## 4. Интеграционная проверка

- [x] 4.1 `pytest -m "not integration"` — всё зелёное
- [x] 4.2 Живая проверка на стенде (секция `LIVE_CHECKS.md`): `sudo aimerge -auDN
      @world -p` на очереди с `[ebuild U ~]` показывает реальное число пакетов в digest и
      в consent-меню (`--ask`), не «0 package(s), tiers unknown»; зафиксировать результат

## Workflow follow-up

- Прогнать `openspec validate fix-queued-plan-parsing --strict` и архивировать изменение по
  завершении
