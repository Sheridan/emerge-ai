# Spec Delta

## MODIFIED Requirements

### Requirement: Собственные флаги emerge-ai
emerge-ai SHALL распознавать собственные флаги `--noninteractive`, `--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences` (и его короткий псевдоним `--i-understand-the-risks`) и `--changelog` в любой позиции argv по полному точному совпадению (не по префиксу), повтор флага идемпотентен, и НЕ передавать их emerge; остальные аргументы передаются без изменений.

#### Scenario: Флаги не видны emerge
- **WHEN** пользователь запускает `emerge-ai --noninteractive -uDN @world`
- **THEN** emerge получает только `-uDN @world`, а emerge-ai включает неинтерактивный режим

#### Scenario: Полностью unattended
- **WHEN** переданы оба собственных флага
- **THEN** emerge-ai работает без вопросов и применяет решения агента на всех risk-tiers

#### Scenario: Точное совпадение вместо префикса
- **WHEN** пользователь передаёт аргумент `--noninteractiveX`
- **THEN** флаг не распознаётся как собственный и передаётся emerge без изменений

#### Scenario: Псевдоним флага ответственности
- **WHEN** запущено `emerge-ai --i-understand-the-risks -uDN @world`
- **THEN** emerge не получает этот аргумент, а emerge-ai работает в режиме полной ответственности

#### Scenario: Оба имени одного флага
- **WHEN** переданы и длинный флаг, и его псевдоним
- **THEN** режим полной ответственности включён однократно, поведение не отличается от одного флага
