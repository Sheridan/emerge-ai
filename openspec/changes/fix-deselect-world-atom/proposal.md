# Proposal

## Why

Вариант «remove … from the world set (emerge --deselect …)» подставляет в слот
`atom` CPV из находки (`triage.py:271-273` — `atom=f.cpv`), то есть версию-кандидата
из вывода emerge, а не запись world-файла. Живой прогон показал
`emerge --deselect sys-firmware/edk2-bin-202608_p1` →
`!!! 'sys-firmware/edk2-bin-202608_p1' is not a valid package atom` (rc 1): для
portage атом с версией без оператора — не атом, а в world лежит
`sys-firmware/edk2-bin`. Валидатор слота это пропускает: `ATOM_RE`
(`whitelist.py:33-35`) делает оператор необязательным, а членство проверяется
только по `cat/pkg` (`whitelist.py:86-96`), поэтому заведомо неисполнимый вариант
попадает в меню как «исполнимый».

Замена CPV на `=<cpv>` хуже текущего поведения. `action_deselect`
(`_emerge/actions.py:2027`) сравнивает аргументы с записями world через
`Atom.intersects()` с охранкой слотов, поэтому версионный атом не пересекается с
неверсионной записью world и выдает `No matching atoms found in "world" favorites
file...` с **кодом выхода 0** — прогон записал бы это в аудит как успешную починку,
`_consent_replan` (`cli.py:1101-1123`) снова увидел бы degraded-вердикт, и меню
предложило бы тот же вариант (число раундов не ограничено, `cli.py:1147`).

## What Changes

- Атом deselect резолвится из world-файла и передаётся **дословно, как записан**
  (`sys-firmware/edk2-bin`, `sys-devel/gcc:14`); CPV находки больше не попадает в
  argv. Живая проверка `--deselect --pretend` на этом хосте:

  | атом | вывод emerge | rc |
  |---|---|---|
  | `sys-firmware/edk2-bin-202608_p1` (ныне) | `!!! not a valid package atom` | 1 |
  | `=sys-firmware/edk2-bin-202608_p1` | `No matching atoms found in "world"` | **0** |
  | `=sys-firmware/edk2-bin-202408_p1` (установленная) | `No matching atoms` | **0** |
  | `sys-firmware/edk2-bin:0` | `No matching atoms` | **0** |
  | `sys-firmware/edk2-bin` | `Would remove sys-firmware/edk2-bin` | 0 |
  | `sys-devel/gcc` | `Would remove sys-devel/gcc`, `gcc:14`, `gcc:15` | 0 |
  | `sys-devel/gcc:14` | ровно `sys-devel/gcc:14` | 0 |

- Если у пакета в world несколько записей (`sys-devel/gcc`, `gcc:14`, `gcc:15`),
  предлагается **отдельный вариант на каждую запись**; голый `cat/pkg`, снимающий
  записи пакета все сразу, не предлагается никогда.
- Валидатор слота `atom`: точное совпадение со строкой world-файла (плюс
  format-проверка, отклоняющая CPV и версионные формы без оператора) — и на
  построении меню, и на TOCTOU-перепроверке (`whitelist.py:203`).
- `whitelist.execute` для `emerge-deselect` перечитывает world после запуска и
  честным статусом сообщает, был ли эффект: запись осталась → статус `no-effect`
  (не `executed`), отдельная аудит-запись, вариант не считается починкой и в этом
  прогоне больше не предлагается.
- Формулировки (заголовок варианта, `undo: emerge --noreplace <атом>`) используют
  тот же дословный атом. `--noreplace` остаётся корректной отменой и для
  установленного пакета: portage дописывает favorites и для nomerge-узлов
  (`_emerge/depgraph.py:11470 nomerge_favorites`).
- Не меняется: состав белого списка команд, бэкап world для `emaint --fix world`,
  текст отмены как механическая строка, порядок «аудит до исполнения».

## Capabilities

### New Capabilities

- нет

### Modified Capabilities

- `repair-actions`: требование «Род действий „белая команда“» уточняется — слот
  deselect валидируется как **дословная** строка world-файла, а исполнение
  проверяется по факту (запись исчезла); новое требование «Вариант deselect
  строится по записям world, а не по CPV находки» — разрешение атома из world,
  отдельный вариант на каждую запись пакета, запрет голых `cat/pkg`, отсутствие
  повтора варианта без эффекта в одном прогоне.

## Impact

- `src/emerge_ai/triage.py`: `candidates()` — разрешение атома deselect из
  `world` (одна запись → вариант, N записей → N вариантов, ноль → advice как
  сейчас); тексты и `atom` строятся из найденной строки world.
- `src/emerge_ai/whitelist.py`: `ATOM_RE`/`_validate_atom` — отсев CPV и
  версионных форм без оператора, членство = точное совпадение со строкой world;
  `execute()` — post-check перечитыванием world, статус `no-effect` + аудит.
- `src/emerge_ai/consent.py`: `menu_specs(..., exclude=...)` — не предлагать
  варианты, уже исполненные без эффекта; заголовок/`undo` из дословного атома.
- `src/emerge_ai/agent.py`: `_finding_variants` наследует то же разрешение (ключи
  и actions общего источника остаются идентичными меню).
- `src/emerge_ai/cli.py`: `_consent_execute` (`cli.py:1077-1086`) учитывает
  `status == "no-effect"` — не журналирует как починку, печатает честное
  сообщение, помечает ключ варианта в no-effect множество прогона.
- Тесты: `tests/test_whitelist.py` (`:44-46`, `:67-68`, `:85-88` закрепляют
  нынешнюю снисходительную валидацию), `tests/test_triage.py:152-161`,
  `tests/test_agent.py:743-757`, `tests/test_consent.py:152-171`, плюс новые
  кейсы: несколько world-записей одного пакета, no-effect, дословный слот-атом.
- Docs: README:229 (`emerge --deselect <атом>` — атом = запись world) и запись в
  `LIVE_CHECKS.md` (живая проверка `--deselect --pretend` и фактического
  deselect-эффекта — за пользователем).
- Не затрагиваются: `emaint --check/--fix world`, etcupdate-канал, правки
  `package.*`, оверлей, точки восстановления.
- Вне области: deselect записей `world_sets` (`@set`, portage поддерживает
  `--deselect @name` — `actions.py:2834`; на этом хосте `world_sets` пуст, форма
  `@…` текущим `ATOM_RE` не выражается); исправление повреждённого world-файла
  (это `emaint --fix world`).
