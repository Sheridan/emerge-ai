# Proposal

## Why

REVIEW_NOTES L6 напоминает: live-ebuild без стабильных версий допустим по спеке,
но README должен объяснять keywording и live-природу пакета. Перевирка при
подготовке apply показала, что более ранняя версия этого проposal опиралась на
ложную посылку («единственный ebuild — `emerge-ai-0.1.0.ebuild`, файла
`emerge-ai-9999.ebuild` нет, README указывает в никуда»). Фактически:
единственный ebuild — `packaging/app-portage/emerge-ai/emerge-ai-9999.ebuild`
(`EAPI=8`, `distutils-r1` + `git-r3`,
`EGIT_REPO_URI=https://github.com/Sheridan/emerge-ai.git`,
`EGIT_BRANCH="master"`, live-статус вытекает из git-r3/версии 9999, без
`KEYWORDS`), и секция «Установка» README `:8-31` уже ему соответствует —
копирование в оверлей, `ebuild … manifest`, `emerge -1av` применимы дословно.

Из L6 остаются два реальных пробела:

- шаг 3 README показывает только `app-portage/emerge-ai **` без объяснения
  различия с явным `~arch` (`~amd64`) — пользователь получает избыточно широкую
  маску как единственный вариант;
- нет live-предупреждения: ставится HEAD `master`, а не релиз; Manifest
  генерируется локально; воспроизводимость требует фиксации коммита
  (`EGIT_COMMIT`).

## What Changes

- Шаг 3 README («Разрешить live-версию»): показать оба варианта
  accept_keywords — `**` (все архитектуры, осознанный выбор для live git-r3) и
  явный `~amd64` — с одним предложением про различие.
- Новый короткий блок после шага 4: live-предупреждение (HEAD `master`,
  локальный Manifest, фиксация коммита через `EGIT_COMMIT`); master-vs-
  default-ветка помечается известным вопросом packaging.
- Цепочки команд шагов 1–4 не переписываются — они уже верны.
- Packaging-файлы не меняются (правка ebuild/KEYWORDS/`EGIT_BRANCH` —
  отдельные changes).

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

(нет — README документация установки, поведение инструмента не меняется,
`skip_specs: true`)

## Impact

- **Docs**: `README.md` шаг 3 (блок `package.accept_keywords`) + новый абзац
  live-предупреждения после шага 4.
- **Код/упаковка**: без изменений; `emerge-ai-9999.ebuild` остаётся единственным
  ebuild.
- **Риски**: нулевые для кода; текстовый дрейф README при будущем изменении
  packaging — риск тот же, что и раньше.
