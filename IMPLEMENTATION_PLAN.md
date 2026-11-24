# План реализации 26 OpenSpec-изменений

Источник замечаний: `REVIEW_NOTES.md`. Каждое замечание покрыто change в
`openspec/changes/<имя>/` (валидны, `--strict`). Реализация начинается **только
по явной команде на apply** конкретного change — план сам по себе кода не трогает.

## Принципы

1. **Одно change = один цикл**: apply по tasks.md → тесты → коммит →
   `openspec archive` (синхронизация главных спеков). Архивировать сразу после
   мержа: последующие дельты копируют тексты требований из главного спека,
   база должна быть актуальной (особенно `agent-loop-consent`, `system-rollback`,
   `cli-compat`).
2. **Ворота качества после каждого change**: `python -m pytest -q -m "not integration"`
   (база — 247 passed, 10 deselected) и `openspec validate --all`.
   В конце каждой волны — прогон `LIVE_CHECKS.md` на живом хосте, если есть доступ.
3. **Порядок внутри волны — по зависимостям**; волны последовательны.
   Параллелить волны можно только в отдельных worktree и только 0↔1 (несовпадающие
   файлы); волны 2–4 идут строго последовательно.
4. Коммиты по конвенции репозитория (`fix(...)`, `feat(...)`, `test(...)`, `docs(...)`);
   в каждом — ссылка на change.

## Граф зависимостей (сжатый)

```
M10 ──► M4, M11
H1  ──► L3(-a -p часть)
H6  ──► L5, H2, H3
M5  ──► H2 ──► H5 ──► H4, M13
M3  ──► M2 (сохранить errors="replace" в новых путях чтения)
```

## Волна 0 — гигиена, доки, мёртвый код (9 изменений, все S/M)

Независимы от остального; чистят базу перед крупными правками `cli.py`/`runner.py`.

| # | Change | Id | Суть | Размер |
|---|--------|----|------|--------|
| 0.1 | fix-live-checks-typo | L1 | опечатка в LIVE_CHECKS.md | S |
| 0.2 | remove-manifest-artifact | L7 | `git rm manifest` + `.gitignore` | S |
| 0.3 | note-overlay-keywords-docs | L6 | README: установка из личного оверлея, `~arch`, live-риск | S |
| 0.4 | overlay-unit-tests | L4 | `tests/test_overlay.py` на tmp-корнях | M |
| 0.5 | remove-unused-run-emerge | M8 | удалить мёртвый `runner.run_emerge` + импорт | S |
| 0.6 | remove-enrich-hook | M7 | удалить `hooks.py` и вызовы; тест `--pretend` переписать с сохранением assert'ов | S |
| 0.7 | fix-confirm-stream-param | L2 | `confirm()`: читать из переданного stream (или убрать параметр — по design) | S |
| 0.8 | lenient-emerge-decoding | M3 | `errors="replace"` на всех путях чтения вывода emerge | S |
| 0.9 | split-emerge-stderr | M2 | два потока чтения, stderr отдельно; signature `(rc, text)` не менять | M |

## Волна 1 — поток `/etc`-конфигуровки (3 изменения, одна зона `cli._etc_flow`)

Идти подряд: все трое правят одно семейство функций, конфликтов не будет только
последовательно.

| # | Change | Id | Суть | Размер |
|---|--------|----|------|--------|
| 1.1 | fix-etc-confirm-fn | M6 | убрать декоративный `confirm_fn` из `_etc_flow` (решение design — удаление) | S |
| 1.2 | fix-etc-web-fetch-stub | M1 | web-контекст по пакету (packages.gentoo.org / поиск wiki), таймауты → пустой контекст | M |
| 1.3 | etc-update-language | M12 | `cfg.resolved_language()` в `etc_system`/`build_merge_prompt`/`llm_decide` | M |

## Волна 2 — конфиг и LLM-обогащение (3 изменения)

| # | Change | Id | Суть | Размер |
|---|--------|----|------|--------|
| 2.1 | align-config-schema | M10 | ключи под спек + алиасы старых с warning; синхронизация шаблона пакета и README | M |
| 2.2 | llm-plan-enrichment | M4 | LLM-сводка плана поверх детерминированного дайджеста; сбой LLM не рвёт план | M |
| 2.3 | auto-changelog-digest | M11 | changelog-дайджест прогона по опции `changelog_digest` (из 2.1) | M |

## Волна 3 — CLI: план-фаза, мутационный путь, гейт (8 изменений)

Ядро ревью. Порядок обязателен.

| # | Change | Id | Суть | Зависит | Размер |
|---|--------|----|------|---------|--------|
| 3.1 | fix-ask-pretend-combo | H1 | pretend побеждает: при `-p` merge не запускается | — | S |
| 3.2 | cover-config-edit-and-ask-pretend | L3 | unit-тесты `config_edit` + e2e `-a -p` | 3.1 | M |
| 3.3 | enforce-systemd-only | M9 | fail-closed детект systemd до мутаций (rc 6), промпты/hints к systemd | — | M |
| 3.4 | plan-before-plain-merge | H6 | план-фаза (резолв→тики→protect→doctor→дайджест) перед любым мутационным прогоном | 3.3 | L |
| 3.5 | avoid-double-resolve-in-plan | L5 | один резолв на план-фазу, вывод побайтно не меняется | 3.4 | M |
| 3.6 | wire-risk-flag | M5 | короткий псевдоним `--i-understand-the-risks` в OWN_FLAGS | — | S |
| 3.7 | wire-autonomy-gate | H2 | гейт тиров + аудит `decisions.log` (fail-closed) перед мутациями; честное сообщение в `-N -a` | 3.4, 3.6 | L |
| 3.8 | wire-rollback-channel | H3 | `--rollback` как отдельный режим + предложение отката после неудачного мержа | 3.4 | L |

## Волна 4 — петля агента (3 изменения, только после 3.7)

| # | Change | Id | Суть | Зависит | Размер |
|---|--------|----|------|---------|--------|
| 4.1 | wire-agent-apply-loop | H5 | `run_agent` (propose→гейт→apply→повтор) вместо advisory-only propose | 3.7 | L |
| 4.2 | wire-journal-writer | H4 | запись применённых фиксов + finalize; дедуп вопросов начинает работать | 4.1 | M |
| 4.3 | handle-agent-limit-exhaustion | M13 | потребление `finish_reason`, вопрос оператора в интерактиве, чистый выход в неинтерактиве | 4.1 | M |

## Финальная приёмка (после 4.3)

- [x] `pytest -q -m "not integration"` — все зелёные; интеграционные — на живом Gentoo.
- [x] `openspec validate --all` — 0 ошибок; `changes/` пуст (все заархивированы).
- [x] README/промпты/LIVE_CHECKS соответствуют фактическому поведению
      (гейт, откат, `-a -p`, enrichment, systemd-only) — сверить по разделу
      «спеки/README врут» в REVIEW_NOTES.
- [ ] Ручной сценарий LIVE_CHECKS целиком: обычный merge (снимок+doctor),
      `-a -p` (без мержа), неинтерактив tier 2 (остановка+аудит), `--rollback`,
      инцидент с применением фикса по согласию и записью в журнал.
- [x] Мусорные артефакты: `manifest` в git отсутствует, `hooks.py`/`run_emerge` удалены.

## Оценка

Всего ≈ 26 change: 12×S, 11×M, 3×L (H5/H6 + H2-H3 как L-кандидаты).
Самые рискованные — 3.4 (перестройка потока CLI) и 4.1 (поведение при сбоях):
у обоих в tasks первые пункты — characterization-тесты текущего поведения.
