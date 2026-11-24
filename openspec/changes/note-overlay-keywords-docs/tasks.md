# Tasks

## 1. Перевирка фактов

- [ ] 1.1 `ls packaging/app-portage/emerge-ai/` и перечитать
      `emerge-ai-9999.ebuild` — подтвердить: единственный ebuild, git-r3/live,
      `EGIT_BRANCH=master`, без `KEYWORDS`; команды README:13-31 соответствуют
      реальным файлам (имена существуют, пути совпадают)

## 2. Примечания README

- [ ] 2.1 Шаг 3: показать оба варианта accept_keywords — `app-portage/emerge-ai
      **` и явный `~amd64` — с одним предложением про различие (широкая маска
      для live git-r3 vs конкретная архитектура); не толкать к избыточно
      широкой маске
- [ ] 2.2 Live-предупреждение после шага 4: ставится HEAD `master` (не релиз),
      Manifest локальный (генерируется `ebuild manifest`), фиксация коммита —
      `EGIT_COMMIT`; master-vs-default-ветка — известный вопрос packaging
      (ebuild в этом change не правим)

## 3. Проверка

- [ ] 3.1 Команды из секции «Установка» механически применимы к файлам
      репозитория; `grep -n 9999 README.md` даёт только осмысленные упоминания
- [ ] 3.2 `openspec validate "note-overlay-keywords-docs"`
