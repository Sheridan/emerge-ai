# Proposal

## Why

Канал правки `package.*` строит имя файла по имени вида (`package.<kind>`), и для
вида `accept_license` это даёт `/etc/portage/package.accept_license` — файл,
которого в portage не существует: лицензии читаются из `package.license`
(`portage/package/ebuild/_config/LicenseManager.py` знает только это имя, строки
`package.accept_license` в дереве portage нет). Запись при этом выглядит
успехом: строка с аудит-маркером написана, прогон перезапущен, а мердж не
изменился — то есть починка класса `license` (он классифицируется
`incident.py` и по лестнице ведёт именно в `package-edit`, `ladder.py:20`)
даёт тихий no-op вместо починки. Дефект воспроизводится на любой раскладке
`/etc/portage` и не связан с каталогами, поэтому вынесен из
`fix-package-edit-directory-target` (там он зафиксирован как отдельный:
`proposal.md:65-67`, `design.md:50-51`).

## What Changes

- Отображение «вид правки → имя файла» становится явным и однократно
  определённым: `accept_license` пишется в `package.license`, остальные виды —
  в `package.<kind>` как сейчас. Внутреннее имя вида НЕ переименовывается:
  `accept_license` остаётся (оно зеркалит переменную `ACCEPT_LICENSE`, и оно
  уже в `KINDS`, в текстах отмены и в подсказке модели
  `prompts/rules/20-ladder.md`).
- Это же имя используется записью, отменой (`remove_by_run`), обзором
  (`get_package_edit_lines`), текстом отмены (`undo_text`/`UNDO_TABLE`) и
  формулировками consent — разойтись они не могут, потому что источник один.
- Раскладка из `fix-package-edit-directory-target` применяется к новому имени
  на тех же правах: каталог `package.license` → запись в
  `package.license/<category>`, резерв `package.license/aimerge` для строк
  без категории; файлы `package.accept_license` канал больше ни при каких
  условиях не создаёт.
- Ни один существующий путь не меняет поведение: сегодня ни один продюсер не
  порождает вид `accept_license` (`agent.typed_variants` даёт `unmask` и
  findings-driven `accept_keywords`, `consent.menu_specs` — тоже
  `accept_keywords`), так что правка убирает скрытый дефект, а не меняет
  текущий вывод команд.
- Инвариант вместо молчаливого дрейфа: таблица «вид → имя файла» покрыта
  тестом, который сверяет её с именами, которые читает portage, и с `KINDS`
  (новый вид без записи в таблице не появится).

## Capabilities

### New Capabilities

- нет

### Modified Capabilities

- `repair-actions`: новое требование «Имя файла канала правки — то, что читает
  portage» — отображение вида в имя файла, читаемое portage (`accept_license` →
  `package.license`), единый источник этого имени для записи/отмены/обзора/
  формулировок, применимость каталожной раскладки к тому же имени, отсутствие
  файлов, которые portage не читает.

## Impact

- `src/aimerge/config_edit.py`: таблица `CHANNEL_FILE` + `channel_file(kind)`;
  `resolve_package_target`, `destination_label`, `UNDO_TABLE`, `undo_text`,
  `package_files` переходят на неё. `KINDS` не меняется.
- `src/aimerge/cli.py`: сообщение дубль-проверки `package.<kind>: '…' already
  present` печатает имя канала из той же таблицы (иначе оно расходится с
  фактическим файлом правки).
- Порядок применения: после `fix-package-edit-directory-target` — правка
  опирается на появившиеся там `resolve_package_target`/`package_files`/
  `destination_label`; требования дельт не пересекаются, но архивировать
  раньше нужно тот change, иначе `repair-actions` пополнится требованием,
  ссылающимся на ещё не существующее разрешение цели.
- Тесты: `tests/test_config_edit.py` (имя канала для лицензий на файловой и
  каталожной раскладке, отмена/обзор по нему, инвариант отображения для всех
  видов), `tests/test_cli_integration.py` (сообщение о дубле называет имя
  канала). `tests/test_consent.py` не меняется: `menu_specs` правки лицензий не
  порождает, её формулировка для лицензий проверяется через `undo_text`.
- Docs: README — имя файла лицензий в описании канала правки; запись в
  `LIVE_CHECKS.md` (проверка, что после правки лицензий появился
  `package.license`, а не `package.accept_license`, и мердж учёл лицензию).
- Не затрагиваются: белый список команд, etcupdate-канал, оверлей, env-retry
  (`ACCEPT_LICENSE` как переменная окружения — другой канал, `sandbox.py:32`),
  точки восстановления.
- Вне области: миграция уже записанных `package.accept_license` (их на живых
  хостах нет — продюсера вида не было); поддержка `package.provided` и
  new-style `packages.*`.
