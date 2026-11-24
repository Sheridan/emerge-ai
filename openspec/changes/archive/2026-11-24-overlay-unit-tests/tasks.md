# Tasks

## 1. Каркас

- [x] 1.1 `tests/test_overlay.py`: helper `fake_ebuild` (по образцу `test_ladder.py`);
      fixture `fake_ebuild_cmd` — второй потребитель, вынести общий в `tests/conftest.py`
- [x] 1.2 Тест `repos_conf_entry`: `[name]`, `location =`, `priority =`,
      `auto-sync = false`; строка `masters =` — на файле `repos.conf` после `ensure_layout`

## 2. Layout, реестр, Manifest

- [x] 2.1 `ensure_layout` на `tmp_path`: `profiles/repo_name`, `metadata/layout.conf`,
      `repos.conf` содержит entry с `masters =`, повторный вызов не дублирует entry
- [x] 2.2 `load_registry`: нет файла → `{}`; после success-`add_package` — плоская
      структура `cpv → {cpv, source, reason, journal_id, ts}`
- [x] 2.3 `write_manifest`: строки EBUILD и AUX (для `files/...` из `names`),
      MD5/SHA1/SHA256/SHA512 и SIZE; отсутствующий файл и сам `Manifest` пропускаются
      без падения; файлы `files/<pv>` из `add_package` в Manifest пакета НЕ входят
      (as-is, комментарий)

## 3. add/remove

- [x] 3.1 `add_package` success c `ebuild_cmd=`-двойником: ebuild и `files/` в оверлее,
      реестр обновлён (cpv, source, reason, journal_id), `repos.conf` на месте
- [x] 3.2 `add_package` failure: `ebuild_cmd=["false"]` → `RuntimeError`, записи в
      реестре нет (копия ebuild остаётся на диске — as-is); `ebuild_cmd=None` →
      локальный `write_manifest` без внешнего вызова, Manifest с EBUILD-строкой
- [x] 3.3 `remove_package`: существующий cpv → `True` + файл удалён; иной → `False`

## 4. Проверка

- [x] 4.1 `pytest` полностью зелёный без root и живого Portage; `-m integration`
      (`test_overlay_live.py`) по умолчанию пропущен, `test_ladder.py` не задет
- [x] 4.2 Реестр тестов нигде дополнительно не регистрируется (в README перечня нет)
- [x] 4.3 `openspec validate "overlay-unit-tests"`
