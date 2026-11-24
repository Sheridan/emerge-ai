# Tasks

## 1. Перевирка фактов

- [ ] 1.1 `ls packaging/app-portage/emerge-ai/` и перечитать `emerge-ai-0.1.0.ebuild` —
      подтвердить: единственный ebuild, git-r3/live, `EGIT_BRANCH=master`, нет `KEYWORDS`;
      убедиться, что файлов `emerge-ai-9999.ebuild`/`emerge-ai-live-9999.ebuild` нет

## 2. Переписывание секции «Установка»

- [ ] 2.1 `README.md:10` — убрать «live-версия (9999)»: один ebuild `emerge-ai-0.1.0.ebuild`
      (live по природе, git-r3), версия в имени не фиксирует содержимое
- [ ] 2.2 `README.md:15-21` — цепочка `cp`/`ebuild`/`emerge --metadata` на реальное имя
      файла `emerge-ai-0.1.0.ebuild`
- [ ] 2.3 Добавить примечание про accept_keywords: `app-portage/emerge-ai **` для ebuild
      без KEYWORDS и частный случай `~amd64` (сохранить существующий фрагмент
      `package.accept_keywords`, README `:28-30`), одно предложение про различие
- [ ] 2.4 Добавить live-предупреждение: HEAD `master`, локальный Manifest, фиксация
      коммита через `EGIT_COMMIT`; пометить master-vs-default-ветку как известный
      вопрос packaging (без правок ebuild в этом change)

## 3. Проверка

- [ ] 3.1 Команды из README механически применимы к файлам репозитория (каждое имя
      файла существует, пути совпадают); `grep -n 9999 README.md` даёт только
      осмысленные упоминания (или пуст)
- [ ] 3.2 `openspec validate "note-overlay-keywords-docs"`
