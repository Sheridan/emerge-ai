# Tasks

## 1. Загрузчик веб-документации

- [x] 1.1 В `src/emerge_ai/cli.py` добавить `_pkg_docs(sandbox, path) -> list[tuple[str, str]]`: вывод `<cat>/<pn>` из пути под `package.use|package.accept_keywords|package.mask|package.unmask` (регулярка имени пакета) → `https://packages.gentoo.org/packages/<cat>/<pn>`, иначе wiki-поиск `https://wiki.gentoo.org/index.php?search=<q>&fulltext=1` (q — basename без суффиксов `-rN`/`.pre-emerge-ai`/`_etc-update-new`); ответ `web_fetch` → `(url, content)`, ответ `{"error"}`/исключение → предупреждение `ui.warn` в stderr и `[]`
- [x] 1.2 Перед циклом `for newp` в `_etc_flow` создать `Sandbox()` один раз; в веб-фазе (`:172-178`) заменить мёртвое замыкание (`Sandbox()`-в-дефолте, wiki-корень, `r["text"]` → `KeyError`) на `docs = _pkg_docs(sandbox, newp)` при включённом `cfg.web_access`, при выключенном — `docs = []` без запросов

## 2. Изоляция ошибок

- [x] 2.1 Убедиться, что `except Exception` с `etc LLM unavailable` (`:181-183`) остался только вокруг `client_factory`/`llm_decide`: веб-ошибки его больше не достигают (нет `KeyError: 'text'`), файл не пропускается молча

## 3. Тесты

- [x] 3.1 В `tests/test_etcupdate.py` (тесты `_etc_flow` живут там, `:8`): с подменённым `Sandbox.web_fetch` успешный ответ попадает в `docs`, переданные в `llm_decide` (парный `<cat>/<pn>` путь → URL каталога, иной путь → wiki-URL)
- [x] 3.2 Там же: `web_fetch` возвращает `{"error": ...}` → в stderr предупреждение, `llm_decide` вызван с пустым списком документации, `etc LLM unavailable` не напечатано
- [x] 3.3 Там же: `web_access` выключен → `web_fetch` не вызывается вообще
- [x] 3.4 Прогнать `pytest` целиком, все тесты зелёные

## 4. Docs

- [x] 4.1 Сверить README `:154` («документация подтягивается из интернета») с фактическим поведением (каталог пакетов / поиск вики, отказ сети = пустой контекст); при расхождении уточнить формулировку
- [x] 4.2 `openspec validate fix-etc-web-fetch-stub` проходит без ошибок
