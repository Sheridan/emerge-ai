# Tasks

## 1. Общий pre-merge блок в cli.py

- [ ] 1.1 Вынести план-фазу (`run_emerge_capturing(plan_args)` → `plan_fn` → `plan_digest`/`doctor_report`) и protect в единый блок, выполняемый для всех режимов до мутационного прогона; `-p` завершает запуск после него с кодом план-резолва.
- [ ] 1.2 На мутационном пути (plain и merge-продолжение `-a`) печатать дайджест/doctor/info protect в stderr; stdout остаётся выводом emerge. В `-p`/`-a` план-вывод не переносить.
- [ ] 1.3 Перенести protect в общий блок ДО режима подтверждения; сохранить механику `prot.failed` + tier≤4 (abort/подтверждение, exit 5, `cli.py:396-408`) и повторное использование существующей точки при resume (`cli.py:379-385`).
- [ ] 1.4 При недоступном плане (сбой `build_plan`) создавать точку восстановления безусловно; при сбое создания — путь `prot.failed` (D4).
- [ ] 1.5 Cleanup точки, если merge не состоялся (отказ оператора `-a`/`N`, штатный отказ emerge `[Yes/No]`); при INCIDENT — сохранить. После успеха — cleanup как сейчас (`cli.py:413-415`).
- [ ] 1.6 Обычная ветка: после pre-merge блока — `_advance_to_merge` → `run_emerge_capturing` без своего confirm (штатный `[Yes/No]` emerge остаётся), дальнейшая обработка rc/инцидента/агента/`_post_run_digest` не меняется.

## 2. Тесты

- [ ] 2.1 Plain-запуск с tier≤4-пакетом: `protect_fn` вызван до merge-`run_emerge_capturing`, stdin не читался; plain rest-tier — protect не вызван.
- [ ] 2.2 Plain `@world` с tier 1: doctor-отчёт в stderr до merge, stdout совпадает с выводом stub-emerge.
- [ ] 2.3 `-a`: точка создаётся до «Proceed?» («N» → точка удалена cleanup'ом, merge не запущен; «y» → merge, cleanup после успеха).
- [ ] 2.4 Сбой `plan_fn` на plain-пути: предупреждение, точка запрошена безусловно; `prot.failed` → exit 5 (и согласованный продолженный merge — существующий сценарий).
- [ ] 2.5 Регрессия существующих CLI-тестов (`test_cli.py`, `test_cli_integration.py`, `test_enrich_doctor.py`) — число прогонов stub-emerge на план+merge = 2.

## 3. Документация и проверка

- [ ] 3.1 `README.md`: обычный запуск тоже делает префлайт (doctor/дайджест в stderr) и создаёт recovery point; упомянуть двойной резолв и связь с `avoid-double-resolve-in-plan`.
- [ ] 3.2 `pytest` целиком + `openspec validate plan-before-plain-merge --strict`.
