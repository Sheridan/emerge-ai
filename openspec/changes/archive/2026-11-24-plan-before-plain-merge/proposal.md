# Proposal

## Why

Запуск без `--pretend`/`--ask` идёт напрямую в `run_emerge_capturing` (`cli.py:310-324`), минуя план-фазу: нет тиров, `rollback.protect`, doctor-префлайта и дайджеста (замечание H6, REVIEW_NOTES.md:75-83). Тем самым нарушаются два базовых спека: `system-rollback` «Триггер защиты перед установкой» (spec:8-9 — SHALL создавать точку восстановления перед первым merge при tier 1–4, не обусловлен `-a`) и `run-reporting` «Автоматический doctor» (spec:19-24 — сценарий ровно `emerge-ai -uDN @world` без `-a`/`-p`, а `doctor_report` вызывается только из план-ветки, `cli.py:353-355`). `emerge-ai sys-libs/glibc` без флагов сейчас ставит glibc без recovery point.

## What Changes

- План-фаза (pretend-резолв → тирование → protect → doctor → дайджест) выносится на общий путь и выполняется ПЕРЕД любым мутационным прогоном, во всех режимах; `-p` по-прежнему останавливается на ней.
- За merge- прогоном сохраняются: интерактивный вопрос emerge (для обычного запуска — штатный `[Yes/No]` самого emerge, свой «Proceed?» — только при `-a`), пост-запусковый отчёт/агент и cleanup точки после успеха.
- protect добирается до обычного пути; порядок «точка восстановления → подтверждение → merge» единообразен для `-a` и обычного запуска.
- Информационные блоки на мутационном пути (дайджест, doctor, info protect) пишутся в stderr, чтобы stdout остался байт-в-байт passthrough emerge (спек `console-output`).
- Стоимость: каждый мутационный запуск получает дополнительный pretend-резолв; время удваивается на больших world — это предмет связанного `avoid-double-resolve-in-plan` (один резолв на план-фазу).

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `system-rollback`: «Триггер защиты перед установкой» — явная независимость от режима запуска (обычный прогон тоже защищается), сценарии на обычный запуск и на отказ от merge.
- `run-reporting`: «Автоматический doctor» — doctor выполняется на любом подпадающем запуске, включая обычный без `-a`/`-p`; вывод informational-блоков не трогает stdout.

## Impact

- `src/emerge_ai/cli.py` — реконструкция развилки `pretend/ask/plain` (`cli.py:305-425`) в общий pre-merge блок + режимные надстройки.
- `tests/test_cli.py`, `tests/test_cli_integration.py`, `tests/test_enrich_doctor.py` — сценарии обычного запуска с protect/doctor.
- `README.md` — описание поведения обычного запуска (префлайт, точка восстановления).
- Связи: без общего пути недостижимы `wire-rollback-channel` (некому предлагать откат после merge) и автономный мердж `wire-autonomy-gate`; синергия с `avoid-double-resolve-in-plan`.
