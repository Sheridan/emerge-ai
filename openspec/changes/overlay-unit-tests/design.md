# Design

## Context

`overlay.py` целиком параметризован путями: `ensure_layout(repo_root, repos_conf_dir, ...)`,
`load_registry(repo_root)`, `write_manifest(dest_dir, names)`,
`add_package(cpv, repo_root=..., source_dir=..., ebuild_cmd=None)`,
`remove_package(cpv, repo_root=...)`; module-level константы `REPOS_CONF`/`OVERLAY_ROOT`
(`:12-13`) используются только как значения по умолчанию — все тесты могут передавать
`tmp_path` явно. Единственный тест слоя — `tests/test_overlay_live.py`
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
копия ebuild + files/, запись в реестр. Отказная ветка: `ebuild_cmd=["false"]`
→ `RuntimeError` и отсутствие записи в реестре. Фактическое поведение guard'а:
реестр он защищает, но скопированный ebuild на диске остаётся (копия происходит до
вызова `ebuild`) — тестируем как есть, с комментарием; это кандидат на отдельный
change, а не обещание current-кода. При `ebuild_cmd=None` внешнего `ebuild` НИКАКОЙ
не вызывается (никакого `EMERGE_AI_EBUILD` в коде нет) — Manifest считается локально
через `write_manifest`; это и есть «fallback», он тестируется.

**D3. Формат Manifest проверяется структурно, а не побайтово.** Портage-совместимость
важна, но точный набор хеш-алгоритмов может меняться (`_digest_manifest_args` пишет
MD5/SHA1/SHA256/SHA512/SIZE), поэтому assert'ы: наличие строк EBUILD и AUX, все четыре
хеша и SIZE, относительный путь AUX-файла (когда `files/...` передан в `names`).
Альтернатива — фиксированный эталонный
файл: хрупко при смене EAPI/алгоритмов; отвергнута.

## Risks

- [Тесты разойдутся с фактическим поведением (bug в коде закрепится как ожидание)] →
  перед написанием каждая функция прочитана; три фактических странности фиксируются
  assert'ами «как есть» с комментарием: (а) `add_package` кладёт `files/<pv>` в
  `repo_root/cat/files/pv` — вне каталога пакета, поэтому в Manifest пакета они не
  попадают; (б) при отказе `ebuild manifest` копия ebuild остаётся на диске (guard
  гарантирует только чистоту реестра); (в) реестр плоский (`cpv → entry`), версии не
  агрегируются. Каждое расхождение с ожиданиями — кандидат отдельного change, а не
  «правильное» поведение по умолчанию.
- [Дублирование `fake_ebuild_cmd` из test_ladder] → при втором потребителе fixture
  переносится в `tests/conftest.py` (задача в tasks).
