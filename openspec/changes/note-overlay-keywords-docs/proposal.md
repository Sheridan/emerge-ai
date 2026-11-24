# Proposal

## Why

README «Установка» (`README.md:8-30`) расходится с packaging-реальностью. Инструкция
говорит «Для live-версии — распакуйте overlay и скопируйте **live-версию (9999)**»
(`:10`) и даёт команду `ebuild /var/lib/overlay/emerge-ai/app-portage/emerge-ai/emerge-ai-9999.ebuild manifest`
(`:21`) — но файла `emerge-ai-9999.ebuild` в репозитории нет: единственный ebuild —
`packaging/app-portage/emerge-ai/emerge-ai-0.1.0.ebuild`, сам по себе live (git-r3 на
`EGIT_REPO_URI`, `EGIT_BRANCH="master"`), без `KEYWORDS` (маскируется стабильными
архитектурами по умолчанию). Инсталлятор по README спотыкается на первой же команде,
а пользователь без `accept_keywords` не увидит пакет (REVIEW_NOTES L6).

## What Changes

- Секция «Установка» README переписана под фактический файл `emerge-ai-0.1.0.ebuild`
  (копирование в `cp /var/lib/overlay/emerge-ai/app-portage/emerge-ai/`, `ebuild … manifest`,
  `emerge --metadata`, `emerge -av app-portage/emerge-ai`) — без упоминания
  несуществующих `emerge-ai-9999.ebuild` / `emerge-ai-live-9999.ebuild`.
- Добавлено примечание про acceptance keywords: для ebuild без `KEYWORDS` нужен
  `accept_keywords = app-portage/emerge-ai **` в `make.conf`/`package.accept_keywords`
  (или явный `~arch`), с пояснением различия.
- Добавлено live-предупреждение: пакет ставится с HEAD upstream (`EGIT_BRANCH=master`),
 Manifest локальный (генерируется `ebuild manifest` на машине пользователя), для
  воспроизводимости стоит зафиксировать коммит (`EGIT_COMMIT`).
- Packaging-файлы в этом change не меняются (возможное добавление настоящего
  `emerge-ai-live-9999.ebuild` или правка `EGIT_BRANCH` master-vs-main — отдельные
  changes).

## Capabilities

### Modified Capabilities

(нет) — README — документация установки, а не спецификация требований; поведение
инструмента не меняется → `skip_specs: true`.

## Impact

- **Docs**: `README.md:8-30` (секция «Установка» + новые примечания).
- **Код/упаковка**: без изменений; `packaging/app-portage/emerge-ai/emerge-ai-0.1.0.ebuild`
  остаётся единственным ebuild.
- **Зависимости**: независимо; текст примечания про live-ветку согласуется с
  `overlay-unit-tests` (тот же слой — только документация).
