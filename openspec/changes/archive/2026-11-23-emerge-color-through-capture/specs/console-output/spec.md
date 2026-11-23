# Spec Delta

## ADDED Requirements

### Requirement: Раскраска emerge сквозь захват вывода
Поскольку emerge запускается с захваченным stdout и portage в auto-режиме не видит TTY, emerge-ai SHALL подставлять в команду emerge флаг `--color=y`, когда собственный stdout emerge-ai поддерживает цвет (TTY, `NO_COLOR` не задана, `TERM != dumb`). Если пользователь явно задал `--color` в аргументах emerge, подстановка не производится. Сам вывод emerge при этом по-прежнему передаётся без изменений.

#### Scenario: Цветной терминал
- **WHEN** emerge-ai запускает emerge с цветным stdout и пользователь не задавал `--color`
- **THEN** команда emerge содержит `--color=y`, и крашеные строки emerge доходят до терминала без изменений

#### Scenario: Pipe и NO_COLOR
- **WHEN** stdout emerge-ai — pipe или задана `NO_COLOR`
- **THEN** `--color=y` не подставляется и крашеных строк emerge в выводе нет

#### Scenario: Пользовательский --color не перекрывается
- **WHEN** пользователь передал `--color=n` (или иное значение) в аргументах emerge
- **THEN** emerge-ai передаёт emerge ровно эти аргументы без своей подстановки
