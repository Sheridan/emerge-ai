# Tasks

## 1. Удаление артефакта

- [x] 1.1 Убедиться, что `git log --oneline -- manifest` даёт только d886e4a
      (никакого более свежего легитимного использования файла нет).
- [x] 1.2 `git rm manifest` — удалить из индекса и рабочей копии; коммит с
      ссылкой на REVIEW_NOTES L7.

## 2. Защита от повтора

- [x] 2.1 В `.gitignore` добавить строку `/manifest` (якорь в корне) с
      комментарием «pytest live-test stdout artifact (L7)».
- [x] 2.2 Проверить `git check-ignore -v manifest` (срабатывает) и
      `git check-ignore Manifest overlay/Manifest` (не срабатывают).

## 3. Контроль чистоты

- [x] 3.1 Прогон тестов (включая live-тесты оверлея) — `git status` после
      прогона чист, новый `manifest` в корне не появляется.
- [x] 3.2 `git grep -w manifest -- ':!openspec'` — ни код, ни тесты удалённый
      корневой файл не читают (совпадения только `Manifest` оверлея).
