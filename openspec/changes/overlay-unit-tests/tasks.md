# Tasks

## 1. Каркас

- [ ] 1.1 `tests/test_overlay.py`: helper `fake_ebuild` (по образцу `test_ladder.py`);
      fixture `fake_ebuild_cmd` — второй потребитель, вынести общий в `tests/conftest.py`
- [ ] 1.2 Тест `repos_conf_entry`: `[name]`, `location=`, `priority=`, `masters=`

## 2. Layout, реестр, Manifest

- [ ] 2.1 `ensure_layout` на `tmp_path`: каталоги созданы, `repos.conf` содержит entry,
      повторный вызов не дублирует entry
- [ ] 2.2 `load_registry`: нет файла → `{}`; после success-`add_package` — структура
      `cat/pn → имя → cpv/versions/overlay_ebuild`
- [ ] 2.3 `write_manifest`: секции EBUILD и AUX (`files/...`), SHA256/SHA512 и SIZE;
      отсутствующий файл пропускается без падения

## 3. add/remove

- [ ] 3.1 `add_package` success c `ebuild_cmd=`-двойником: ebuild и `files/` в оверлее,
      реестр обновлён, версия в `versions`
- [ ] 3.2 `add_package` failure: `ebuild_cmd=["false"]` → `RuntimeError`, записи в
      реестре нет; `ebuild_cmd=None` → fallback на `EMERGE_AI_EBUILD`/`ebuild`
- [ ] 3.3 `remove_package`: существующий cpv → `True` + файл удалён; иной → `False`

## 4. Проверка

- [ ] 4.1 `pytest` полностью зелёный без root и живого Portage; `-m integration`
      (`test_overlay_live.py`) по умолчанию пропущен, `test_ladder.py` не задет
- [ ] 4.2 Реестр тестов нигде дополнительно не регистрируется (в README перечня нет)
- [ ] 4.3 `openspec validate "overlay-unit-tests"`
