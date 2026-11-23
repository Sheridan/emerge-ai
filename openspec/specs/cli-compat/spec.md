# cli-compat Specification

## Purpose
Определяет совместимость CLI emerge-ai со штатным emerge: сквозную передачу флагов и кодов выхода, собственные флаги режимов, перехват pretend/ask и привязку версии проекта к версии portage.

## Requirements

### Requirement: Passthrough флагов emerge
emerge-ai SHALL принимать полный набор опций emerge, передавать их штатному emerge без изменений и завершаться с кодом выхода запущенного emerge.

#### Scenario: Штатный запуск
- **WHEN** пользователь запускает `emerge-ai -uDN @world` и все сборки завершаются успешно
- **THEN** emerge-ai пробрасывает флаги emerge, печатает его вывод и завершается с кодом 0

#### Scenario: Ошибочный флаг
- **WHEN** пользователь передаёт флаг, неизвестный emerge
- **THEN** emerge-ai показывает штатную ошибку emerge и завершается с его кодом ошибки

### Requirement: Собственные флаги emerge-ai
emerge-ai SHALL распознавать собственные флаги `--noninteractive`, `--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences` и `--changelog` в любой позиции argv по полному точному совпадению (не по префиксу), повтор флага идемпотентен, и НЕ передавать их emerge; остальные аргументы передаются без изменений.

#### Scenario: Флаги не видны emerge
- **WHEN** пользователь запускает `emerge-ai --noninteractive -uDN @world`
- **THEN** emerge получает только `-uDN @world`, а emerge-ai включает неинтерактивный режим

#### Scenario: Полностью unattended
- **WHEN** переданы оба собственных флага
- **THEN** emerge-ai работает без вопросов и применяет решения агента на всех risk-tiers

#### Scenario: Точное совпадение вместо префикса
- **WHEN** пользователь передаёт аргумент `--noninteractiveX`
- **THEN** флаг не распознаётся как собственный и передаётся emerge без изменений

### Requirement: Мета-флаги версии и справки
emerge-ai SHALL распознавать `--version`/`-V` и `--help` только когда они являются первым аргументом argv: напечатать версию (emerge-ai и portage) или собственную справку и завершиться, не проверяя совместимость версий и не запуская emerge. В любой другой позиции эти строки SHALL передаваться emerge как обычные аргументы.

#### Scenario: Версия первым аргументом
- **WHEN** выполнено `emerge-ai --version`
- **THEN** напечатаны версии emerge-ai и portage, emerge не запущен, код выхода 0 (ненулевой — только если portage недоступен)

#### Scenario: Справка первым аргументом при несовместимом portage
- **WHEN** выполнено `emerge-ai --help` и версии portage/emerge-ai несовместимы
- **THEN** напечатана справка по собственным флагам emerge-ai, emerge не запущен, код выхода 0 (гейт совместимости не блокирует справку)

#### Scenario: Мета-флаг не на первой позиции
- **WHEN** выполнено `emerge-ai -p --help`
- **THEN** `--help` передан штатному emerge как аргумент, собственная справка emerge-ai не печатается

### Requirement: Возобновление через --resume
emerge-ai SHALL распознавать `--resume`: при наличии незавершённого run'а emerge-ai — продолжить его с сохранённым контекстом, не передавая `--resume` emerge; при отсутствии такого run'а `--resume` SHALL сохраняться в аргументах и передаваться штатному emerge (возобновление merge'а самого emerge), а запуск обрабатывается emerge-ai как обычный, без возобновления старого run'а.

#### Scenario: Возобновление run'а emerge-ai
- **WHEN** в runs-каталоге есть незавершённый run и выполнено `emerge-ai --resume ...`
- **THEN** run продолжается с сохранённого состояния и контекста инцидента, emerge не получает `--resume`

#### Scenario: Нет run'а emerge-ai — passthrough emerge
- **WHEN** незавершённых run'ов emerge-ai нет и выполнено `emerge-ai --resume`
- **THEN** emerge запущен с `--resume` как есть (штатная семантика emerge); старый run emerge-ai не возобновляется, вместо этого регистрируется обычный новый run

### Requirement: Привязка версии к portage
Версия emerge-ai SHALL равняться версии portage, на котором он выполняется. При запуске emerge-ai SHALL проверять, что `major.minor` версии portage равны `major.minor` версии emerge-ai; при несовпадении — вывести сообщение и завершиться с ненулевым кодом, не выполняя никаких действий emerge. Проверка SHALL не применяться к режимам, которые не запускают emerge и не используют python-API portage: `--version`/`-V`, `--help`, `--changelog`.

#### Scenario: Совместимые версии
- **WHEN** emerge-ai 3.0.82.2 запущен с portage 3.0.83
- **THEN** проверка проходит (3.0 == 3.0) и работа продолжается

#### Scenario: Несовместимые версии
- **WHEN** emerge-ai 3.0.82.2 запущен с portage 3.1.0
- **THEN** emerge-ai выводит сообщение о несовместимости python-API и выходит с ненулевым кодом

#### Scenario: Обходят проверку
- **WHEN** несовместимый portage и выполнено `emerge-ai --changelog`
- **THEN** дайджест новостей формируется без запуска emerge, код выхода 0

### Requirement: Поддержка только systemd
emerge-ai SHALL поддерживать только systemd-системы: рекомендации агента и системные действия SHALL использовать инструменты systemd (systemctl и т.п.) и SHALL не формировать сценарии для openrc.

#### Scenario: Рекомендация по сервису
- **WHEN** решение требует перезапуска сервиса
- **THEN** агент предлагает действие через systemctl, без упоминания openrc-команд
