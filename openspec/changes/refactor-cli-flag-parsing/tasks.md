# Tasks

## 1. Characterization-тесты (до рефакторинга, должны проходить на текущем коде)

- [x] 1.1 В `tests/test_flags.py` — тесты семантики парсинга: точное совпадение (`--noninteractiveX` не распознаётся и уходит emerge), распознавание own-флагов в любой позиции argv, идемпотентность повторного флага; прогнать `pytest tests/test_flags.py` — зелено на текущем коде
- [x] 1.2 В `tests/test_cli.py` — тесты мета-флагов: `--version`/`-V`/`--help` только как `argv[0]` (напечатано/эмердж не зван), в не-нулевой позиции флаг доходит до emerge-stub; `--help`/`--version` работают при несовместимом portage (rc 0, гейт не блокирует); `--changelog` не упирается в version-gate; прогнать `pytest tests/test_cli.py` — зелено
- [x] 1.3 Тест согласованности таблицы и help (заполняется вместе с 2.1): проверить, что текущий `OWN_FLAG_HELP` содержит каждый флаг из `OWN_FLAGS` построчно (`pytest tests/test_flags.py -k help`) — зелено или осознанно обновить выравнивание как фиксируемое исправление

## 2. Табличный парсер собственных флагов (flags.py)

- [x] 2.1 Заменить `OWN_FLAGS`-кортеж и positional-ветки на маппинг `flag → поле Mode` + цикл с `setattr`; `OWN_FLAG_HELP` генерировать из таблицы фикс-колонкой (устранить расхождение `--changelog`); добавить тест инварианта `set(OWN_FLAGS.values()) == {f.name for f in dataclasses.fields(Mode)}`; прогнать `pytest tests/test_flags.py tests/test_cli.py` — зелено (1.1–1.3 переживают рефакторинг без правок)
- [x] 2.2 В `_flag_kinds`/`flag_present`/`drop_flags` (runner.py) уточнить docstring'ы и имена (что за какие множества отвечает), поведение не менять; прогнать `pytest tests/test_flags.py -k "present or drop"` — зелено

## 3. Хелперы main() и типизация (cli.py, state.py)

- [ ] 3.1 Вынести мета-флаги в `_meta_command(argv) -> int | None` (docstring: правило «только первый аргумент»), `main()` вызывает её; прогнать `pytest tests/test_cli.py -k "version or help"` — зелено
- [ ] 3.2 **Фикс resume**: в `_resolve_resume(...)` при отсутствии незавершённого run'а оставлять `--resume` в emerge_args (ветка «starting fresh» не вырезает флаг); сообщения `resuming`/`starting fresh` внутрь хелпера; новый регрессионный тест в `tests/test_cli_integration.py`: runs-каталог пуст → `cli.main(["--resume"])` → emerge-stub вызван с `["--resume"]`, создан один run, rc=stub (красный до 3.2, зелёный после)
- [ ] 3.3 Ужесточить `state.new_run(argv, mode: Mode)`: удалить dict-ветку и локальный импорт; перевести `tests/test_cli_integration.py:57,141` на `Mode(...)`; прогнать `pytest tests/test_state.py tests/test_cli_integration.py` — зелено

## 4. Интеграционная проверка

- [ ] 4.1 Полный `pytest` — все тесты зелёные; `openspec validate refactor-cli-flag-parsing --strict` без ошибок; сценарии дельты cli-compat покрыты тестами (сверить каждый сценарий с тестом и перечислить соответствие в PR-описании/коммите)
- [ ] 4.2 Ручная smoke-проверка на стенде без live-мутаций: `emerge-ai --help`, `emerge-ai -V`, `emerge-ai -p --help` (справка emerge), пустой runs-каталог + `EMERGE_AI_RUNS_DIR=... emerge-ai --resume` (эмердж получает `--resume`) — поведение совпадает со спекой

## Workflow follow-up

- Архивировать change (`openspec archive`) после ревью пользователем и синка дельты в main-спеку `cli-compat`.
