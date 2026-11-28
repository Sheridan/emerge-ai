# Proposal

## Why

Конsent-диалог показал «merge the queue as shown (0 package(s), tiers unknown)», хотя в очереди
стояли два обновления: разбор `--pretend`-вывода не распознаёт строки статуса с флагами
маскировки (`[ebuild     U ~]`), а fallback-резолвер на живом портедже возвращает пустой план
(элементы `altlist` — объекты `Package` без `.pkg`) и при «починке» через `--nodeps` вернул бы
весь замыканный набор world (627) вместо реально запланированных пакетов. Оператор даёт
согласие на неверно описанное действие — это вопрос безопасности consent-диалога.

## What Changes

- `EBUILD_LINE_RE` распознаёт строки ebuild-статуса с любыми флагами статуса (`~`, `*`, `-` и
  впредь), а не только с буквами `NnUuRrFf`.
- Fallback-резолвер строит план из честного seam: резолвер вызывается как у настоящего emerge
  (без `--nodeps`) и берётся реальный список запланированных к merge (`mergelist` depgraph'а,
  доступ через `portage_compat` — единственный контактный слой); `--nodeps` из `build_plan`
  убран, поскольку он возвращает весь набор set-аргументов как «merge» и пустой `mergelist`.
- `menu_specs`: при недоступном плане (`plan is None`) пункт merge честно говорит «queue
  unknown», а не «0 package(s)»; нулевой пакетный счётчик остаётся легитимным только когда
  очередь действительно пуста.
- Тестовые фейки altlist/mergelist становятся портаж-подобными (`Package.cpv`, `installed`),
  фикстуры включают статус-флаги `U ~`, `U *`, `R ~`.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `run-reporting`: новое требование об очереди плана: очередь = пакеты, запланированные к
  merge (тот же список, что показывает `--pretend`), включая случай маскированных
  статус-флагов в тексте и честный fallback-резолвер; недоступный план отличается от пустого.
- `consent-dialogue`: новое требование «Пункт merge различает недоступную и пустую
  очередь» — «queue unknown» против честного «0 package(s)».

## Impact

- Код: `src/aimerge/digest.py` (regex), `src/aimerge/plan.py` (`build_plan`,
  `_iter_installed_tasks`), `src/aimerge/portage_compat.py` (seam списка merge),
  `src/aimerge/consent.py` (рендер пункта merge при недоступном плане).
- Тесты: `tests/test_digest.py`, `tests/test_plan.py`, `tests/test_portage_compat.py`,
  `tests/test_consent.py`; секция живой проверки в `LIVE_CHECKS.md`.
- Поведение: меню consent и контракт точки восстановления начинают показывать реальное
  число пакетов и tiers; риски — изменение стоимости fallback-резолва (полный резолв вместо
  `--nodeps`), принятый как цена честности.
