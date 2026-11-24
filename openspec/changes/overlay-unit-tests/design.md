# Design

## Context

`overlay.py` целиком параметризован путями: `ensure_layout(repo_root, repos_conf_dir, ...)`,
`load_registry(repo_root)`, `write_manifest(overlay_ebuild, skip=...)`,
`add_package(cpv, ..., repo_root, repos_conf_dir, ebuild_cmd=None)`,
`remove_package(cpv, repo_root, ...)`; module-level константа `REPOS_CONF` (`:13`) в
теле функций не используется. Единственный тест слоя — `tests/test_overlay_live.py`
с маркером `integration` (`pyproject.toml:25-26`, не запускается по умолчанию), который
требует живого дерева Portage и реального `ebuild`. Ошибка в реестре или Manifest
обнаруживается только на машине пользователя.

## Goals / Non-Goals

**Goals:** deterministic-юниты для каждой публичной функции оверлея на `tmp_path`;
success-ветка `add_package` без живого ebuild (через `ebuild_cmd`); проверка формата
реестра, repos.conf и Manifest; идемпотентность `ensure_layout`.

**Non-Goals:** интеграционные проверки живым `ebuild`/`emerge` (остаются под маркером
`integration`); рефакторинг `overlay.py`; покрытие `config_edit`/`fixes` (у них свои
наборы в `test_ladder.py`).

## Decisions

**D1. Без monkeypatch — параметризация уже есть.** В отличие от `paths.py`-шных модулей,
оверлейные функции принимают `repo_root`/`repos_conf_dir` аргументами (константа
`REPOS_CONF` в коде не читается), поэтому достаточно передавать `tmp_path` — моки
пути не нужны и только скрывали бы реальный контракт. Альтернатива из REVIEW_NOTES
(«monkeypatch `overlay.REPOS_CONF`/`OVERLAY_ROOT`») отвергнута: патчилось бы
неиспользуемое.

**D2. Success-ветка `add_package` через `ebuild_cmd`-двойник.** Параметр `ebuild_cmd`
позволяет подставить команду, которая «делает manifest» без Portage (как `fake_ebuild_cmd`
в `tests/test_ladder.py`: скрипт, пишущий файл Manifest). Это даёт полный путь:
копия ebuild + files/, запись в реестр, `repos.conf`. Отказная ветка: `ebuild_cmd=["false"]`
→ `RuntimeError` и отсутствие записи в реестре (осиротевший ebuild — то, что guard
в `add_package` обещает prevention-мандатом).

**D3. Формат Manifest проверяется структурно, а не побайтово.** Портage-совместимость
важна, но точный набор хеш-алгоритмов может меняться (`--force` + `_hashes`), поэтому
assert'ы: наличие секций EBUILD/AUX, хотя бы один `SHA256`/`SHA512`, SIZE-поле, имя
AUX-файла с относительным путём `files/...`. Альтернатива — фиксированный эталонный
файл: хрупко при смене EAPI/алгоритмов; отвергнута.

## Risks

- [Тесты разойдутся с фактическим поведением (bug в коде закрепится как ожидание)] →
  перед написанием каждая функция прочитана; подозрительные места (например, `skip`
  для `files/` не пробрасывается из `add_package`) проверяются отдельным assert'ом и,
  при расхождении с мандатом, фиксируются TODO со ссылкой на новый change, а не
  закрепляются молча.
- [Дублирование `fake_ebuild_cmd` из test_ladder] → при втором потребителе fixture
  переносится в `tests/conftest.py` (задача в tasks).
