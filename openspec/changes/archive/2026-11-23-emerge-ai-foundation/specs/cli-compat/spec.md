# Spec Delta

## Purpose

Определяет совместимость CLI emerge-ai со штатным emerge: сквозную передачу флагов и кодов выхода, собственные флаги режимов, перехват pretend/ask и привязку версии проекта к версии portage.

## ADDED Requirements

### Requirement: Passthrough флагов emerge
emerge-ai SHALL принимать полный набор опций emerge, передавать их штатному emerge без изменений и завершаться с кодом выхода запущенного emerge.

#### Scenario: Штатный запуск
- **WHEN** пользователь запускает `emerge-ai -uDN @world` и все сборки завершаются успешно
- **THEN** emerge-ai пробрасывает флаги emerge, печатает его вывод и завершается с кодом 0

#### Scenario: Ошибочный флаг
- **WHEN** пользователь передаёт флаг, неизвестный emerge
- **THEN** emerge-ai показывает штатную ошибку emerge и завершается с его кодом ошибки

### Requirement: Собственные флаги emerge-ai
emerge-ai SHALL распознавать `--noninteractive` и `--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences` до передачи аргументов в emerge и НЕ передавать их emerge.

#### Scenario: Флаги не видны emerge
- **WHEN** пользователь запускает `emerge-ai --noninteractive -uDN @world`
- **THEN** emerge получает только `-uDN @world`, а emerge-ai включает неинтерактивный режим

#### Scenario: Полностью unattended
- **WHEN** переданы оба собственных флага
- **THEN** emerge-ai работает без вопросов и применяет решения агента на всех risk-tiers

### Requirement: Привязка версии к portage
Версия emerge-ai SHALL равняться версии portage, на котором он выполняется. При запуске emerge-ai SHALL проверять, что `major.minor` версии portage равны `major.minor` версии emerge-ai; при несовпадении — вывести сообщение и завершиться с ненулевым кодом, не выполняя никаких действий emerge.

#### Scenario: Совместимые версии
- **WHEN** emerge-ai 3.0.82.2 запущен с portage 3.0.83
- **THEN** проверка проходит (3.0 == 3.0) и работа продолжается

#### Scenario: Несовместимые версии
- **WHEN** emerge-ai 3.0.82.2 запущен с portage 3.1.0
- **THEN** emerge-ai выводит сообщение о несовместимости python-API и выходит с ненулевым кодом

### Requirement: Поддержка только systemd
emerge-ai SHALL поддерживать только systemd-системы: рекомендации агента и системные действия SHALL использовать инструменты systemd (systemctl и т.п.) и SHALL не формировать сценарии для openrc.

#### Scenario: Рекомендация по сервису
- **WHEN** решение требует перезапуска сервиса
- **THEN** агент предлагает действие через systemctl, без упоминания openrc-команд
