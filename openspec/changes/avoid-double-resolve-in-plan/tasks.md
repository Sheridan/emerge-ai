# Tasks

## 1. Извлечение плана из pretend-вывода

- [ ] 1.1 `src/emerge_ai/plan.py`: `build_plan_from_output(output, emerge_args, tier_service, *, fallback=build_plan, system_atoms=None)` — ANSI-strip, regex-константы `digest` (импорт, не копирование), отсечение `::repo`, дедуп с сохранением первого вхождения, тир через `tier_service.classify`; пустой разбор → `fallback(emerge_args, tier_service)`.
- [ ] 1.2 `tests/test_plan.py` (расширить): парные тесты эквивалентности с `build_plan`-резолвер-стабом на pretend-фикстуре (ANSI-коды, `::repo`, masked `[cat/pkg ver]`, slotted-CPV, порядок merge); пустой/неразбираемый вывод (`-qq`, мусор) → вызван fallback; дедуп повторяющихся строк.

## 2. Замена вызова в CLI

- [ ] 2.1 `src/emerge_ai/cli.py:349`: план-фаза вызывает `build_plan_from_output(output, emerge_args, tier_service)` (переменная `output` из `run_emerge_capturing` уже в области видимости); инъективный `plan_fn` сохранить.
- [ ] 2.2 CLI/replay-тесты: байтовая идентичность stdout/stderr и `run.plan` на существующих replay-фикстурах; счётчик вызовов резолва-стаба == 0 при разобранном pretend-выводе и == 1 на `-qq`; дайджест/doctor/rc не изменились.

## 3. Проверка

- [ ] 3.1 `pytest` целиком; `openspec validate avoid-double-resolve-in-plan --strict`.
