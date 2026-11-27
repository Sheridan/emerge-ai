# Design

## Context

Consent-диалог показал `merge the queue as shown (0 package(s), tiers unknown)` при живой
очереди из двух обновлений. Два независимых слома: разбор `--pretend`-текста
(`EBUILD_LINE_RE`) не переносит флаги статуса `~`/`*`/`-` в скобке `[ebuild     U ~]`, а
fallback-резолвер (`build_plan` → `_iter_installed_tasks`) на живом portage возвращает пусто:
элементы `graph.altlist()` — объекты `_emerge.Package.Package` без `.pkg`/`.merge`/`_pkg`, и
ни одна ветка извлечения cpv не срабатывает. Всё чтение portage живёт в `portage_compat`
(единственная точка контакта, design D1/D2 исходной спеки), и новый seam обязан остаться там.

Ограничения: основной источник очереди — уже захваченный pretend-вывод план-фазы
(no-double-resolve); второй полный резолв допустим только как fallback. Пустая очередь —
легитимное состояние («обновлять нечего»), её показывать можно; нельзя показывать пустую
очередь, когда план построить не удалось.

## Goals / Non-Goals

**Goals:**
- очередь = ровно то, что emerge соберётся мержить (тот же список, что в `--pretend`), при
  любых флагах статуса в тексте и при честном fallback-резолвере;
- «план недоступен» ≠ «0 пакетов» в consent-меню;
- тестовые фейки portsage-подобные, фикстуры содержат статус-флаги.

**Non-Goals:**
- парсинг `[blocks B ]`, `[unmerge ...]`, `[binary ...]`-строк (вне текущего контракта
  очереди ebuild'ов);
- изменение триггера снапшота (`system-rollback` уже трактует «тиры не определены» как
  «защищаемые есть» — с починенным планом это перестаёт врать само собой);
- LLM-часть consent-диалога (отдельный change `consent-question-channel`).

## Decisions

### D1. Регулярка ест любое содержимое статусной скобки

`EBUILD_LINE_RE = r"^\[ebuild\s+[^\]]+\]\s+(\S+)"` вместо перечисления букв `[NnUuRrFf]*`.
Флаги маскировки/маски (`~`, `*`, `-`) и всё, что portage придумает впредь, попадают в скобку
между пробелами; префикс `[ebuild` отличает строку от `[blocks B ]`/`[unmerge ]`. Группа
остается один токен CPV, `_clean_cpv` не меняется. Альтернатива — расширенный класс
`[A-Za-z~*\-]*` — отвергнута: требует правки при каждом новом флаге.

### D2. Честный seam fallback-резолвера (верифицировано на живом хосте)

Замерено на стенде (Gentoo, portage 3.0.x): с `--nodeps` и `action="build"` `altlist()` —
весь замыканный набор world (627–628 элементов, у всех `operation='merge'`,
`installed=False`), `mergelist` пуст. Без `--nodeps`, с опциями, разобранными самим portage
(`_emerge.main.parse_opts` от argv пользователя; `insert_optional_args` он вызывает сам —
двойное применение ломает argv), и форсированными `--pretend`/`--quiet` при снятом `--ask`:

```
action, opts, files = parse_opts(argv)   # ("None"|action, {"--update": True, ...}, files)
opts["--pretend"] = True; opts["--quiet"] = True; opts.pop("--ask", None)
cfg = load_emerge_config(action=action, args=files, opts=opts)
success, graph, _ = backtrack_depgraph(...)
queue = [p.cpv for p in graph.altlist() if not p.installed]   # == очередь emerge --pretend
```

даёт ровно `['dev-libs/jemalloc-5.4.0-r2', 'app-misc/yazi-26.9.1']` — те два `[ebuild U ~]`
из pretend-вывода. То есть `altlist`, отфильтрованный по `not installed`, и есть
«запланированные к merge»; `mergelist` под `--pretend` пуст и использовать его нельзя.
Новые помощники в `portage_compat` (единственный слой): `parse_emerge_opts(argv)` и
`queued_cpvs(graph)`. Альтернатива «признать fallback мёртвым и показывать plan unavailable»
отвергнута оператором: план должен считать реальную очередь, а не деградировать.

### D3. `build_plan` резолвит те же argv, что получил emerge

`build_plan(emerge_args, ...)` парсит `emerge_args` через `portage_compat.parse_emerge_opts`
(пользовательские флаги `-uDN`, атомы/сеты — как их видит emerge; `--ask` к этому моменту
снят `drop_flags` в cli), вместо `{"--nodeps": True}` + «атомы без флагов, action="build"».
`_iter_installed_tasks` удаляется; извлечение cpv — `queued_cpvs`. Цена: fallback платит
полным резолвом (без `--nodeps` дороже) — принята как цена честности; основной путь
(`build_plan_from_output`) резолва не делает вовсе.

### D4. `menu_specs`: plan `None` — «queue unknown», пустой план — честный «0»

`plan is None` (резолвер упал/портage недоступен — в cli это оставленный `None` после
исключения в enrichment) → пункт merge: `merge the queue as shown (queue unknown: the plan
could not be built)` плюс tiers `unknown`. Пустой план → `merge the queue as shown
(0 package(s), nothing to merge)`. `protect_contract` для `plan is None` уже консервативен
(точка нужна) — согласован с system-rollback, не меняется.

### D5. Тестовые двойники — портаж-подобные

Fake-`Package` в тестах: атрибуты `cpv: str`, `installed: bool` (никаких `.pkg`); фикстуры
pretend-вывода включают `[ebuild     U ~]`, `[ebuild  N *]`, `[ebuild     R ~]` и живую
строку с `USE=...` после CPV.

## Risks / Trade-offs

- `[^\]]+` шире прежнего: строка вида `[ebuild weird]` матчится — приемлемо, следующий
  `_clean_cpv` требует `cat/pkg-version` с цифрой, мусор отсеивается.
- Полный резолв в fallback — секунды/минуты на большом world; только при нечитаемом
  pretend-выводе.
- `parse_opts` может `sys.exit()` на незнакомом флаге — вызываем только argv, которые уже
  успешно принял настоящий emerge в план-фазе (тот же argv), риск окно теоретическое;
  заворачиваем в `PortageUnavailable` через перехват SystemExit в seam.

## Migration Plan

Обычная выкатка версией пакета; поведение меняется только в отказных ветках (нечитаемый
вывод, недоступный plan). Откат — предыдущая версия, данных не трогает.

## Open Questions

- Показывать ли в пункте merge при `plan is None` подсказку причины (текст исключения
  резолвера) — реализовать по месту, на спеку не влияет.
