# Tasks

## 1. Модуль детекта init

- [ ] 1.1 `src/emerge_ai/init_check.py`: `is_systemd(*, path_exists=..., proc1_comm=...) -> bool` — признак `/run/systemd/system`, fallback `comm == "systemd"`; недоступное/неизвестное состояние → False; текст диагностического сообщения (обнаруженный init) рядом в модуле или ui.
- [ ] 1.2 `tests/test_init_check.py`: systemd-хост (каталог есть), OpenRC (каталога нет, comm=«openrc:init»→False), fallback (каталога нет, comm=«systemd»→True), неизвестно (зонды бросают →False).

## 2. Гейт в CLI

- [ ] 2.1 В `cli.main` после разбора собственных флагов и гейта версии portage — классификация режима: мутационный (plain, merge-продолжение `-a`) против read-only (`-p` solo, `--changelog`, мета-флаги); при `--rollback` (когда появится) — warning-класс (D3).
- [ ] 2.2 Мутационный + не-systemd → `ui.err`-отказ («поддерживаются только systemd-системы; обнаружен: …»), rc 6, до любого `run_emerge_capturing`/protect; read-only + не-systemd → однократное предупреждение в stderr, работа продолжается.
- [ ] 2.3 Инъекция детекта в `main` (параметр-зонд с systemd-дефолтом для тестов — стиль существующих `emerge_binary`/`*_fn`), чтобы существющий suite не менялся точечно.
- [ ] 2.4 CLI-тесты: OpenRC + установка → rc 6, emerge не вызывался (stub-счетчик), stdin не читался; `-p` на OpenRC → предупреждение + штатный pretend-вывод; `--version` → rc 0 без предупреждения-отказа; unknown-init → отказ (fail-closed).

## 3. Тексты и документация

- [ ] 3.1 `prompts/rules/00-role.md`/`10-safety.md`: директива «системные действия — только systemctl/journalctl; openrc-команды не предлагать»; `sandbox.py` не менять (journalctl остаётся, rc-* не добавляем), `tiers.py` не менять.
- [ ] 3.2 `README.md`: prerequisite «требуется systemd», таблица кодов выхода + 6, примечание про read-only режимы на чужом init.
- [ ] 3.3 `pytest` целиком + `openspec validate enforce-systemd-only --strict`.
