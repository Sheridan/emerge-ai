# Proposal

## Why

Оверлей-слой (`src/emerge_ai/overlay.py`) — единственная часть кода, пишущая в файловую
систему Portage (layout, `repos.conf`, реестр `registry.json`, ebuild-копии, Manifest),
и при этом не покрыта юнит-тестами: `tests/test_overlay_live.py` — интеграционный тест
с маркером `integration`, помеченный в самом файле как «Не требует правки» и требующий
живого дерева Portage (реально запускает `ebuild manifest` и `emerge --metadata`). В
`tests/test_ladder.py` есть один сквозной сценарий (`test_overlay_add_registers_and_wins_priority`),
но он не покрывает ни идемпотентность `ensure_layout`, ни формат реестра `load_registry`,
ни состав хешей `write_manifest`, ни ветку отказа `add_package`, ни `remove_package`.
Функции оверлея принимают `repo_root`/`repos_conf_dir` явными аргументами, поэтому
тестируются на `tmp_path` без monkeypatch (REVIEW_NOTES L4).

## What Changes

- Новый файл `tests/test_overlay.py` — юнит-набор без root и без живого дерева:
  - `repos_conf_entry` — формат секции (`[name]`, `location=`, `priority=`, `masters=`);
  - `ensure_layout` — каталоги созданы, entry в `repos.conf`, повтор идемпотентен;
  - `write_manifest` — строки EBUILD и AUX (`files/...`), хеши MD5/SHA1/SHA256 или
    SHA512 + SIZE; отсутствующий файл пропускается без падения;
  - `load_registry` — пустой/отсутствующий файл → `{}`, после записи — корректная
    структура (`cat/pn` → имя → `cpv`/`versions`/`overlay_ebuild`);
  - `add_package` — success с фейковым `ebuild_cmd` (как `fake_ebuild_cmd` в
    `test_ladder.py`), отказ `ebuild_cmd=["false"]` → `RuntimeError` без осиротевшей
    записи в реестре, fallback `ebuild_cmd=None` на `EMERGE_AI_EBUILD`/`ebuild`;
  - `remove_package` — `True` при удалении, `False` при отсутствии.
- Существующие тесты не меняются; живой ebuild остаётся интеграционным маркером.

## Capabilities

### Modified Capabilities

(нет) — спецификация `overlay-patching` описывает требования к самому слою оверлея,
они не меняются; изменение добавляет только тесты (тестовые наборы не специфицируются)
→ `skip_specs: true`.

## Impact

- **Код**: `src/emerge_ai/overlay.py` не изменяется (тесты пишутся под фактическое
  поведение; расхождения — отдельным change).
- **Тесты**: `tests/test_overlay.py`; общий fixture `fake_ebuild_cmd` при необходимости
  переносится из `tests/test_ladder.py` в `tests/conftest.py` (или дублируется).
- **Docs**: README не меняется — в нём нет перечня тестовых файлов (проверено grep).
- **Зависимости**: независимо; смежно с `note-overlay-keywords-docs` (тот же слой).
