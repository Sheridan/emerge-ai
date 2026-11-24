# Spec Delta

## MODIFIED Requirements

### Requirement: Поддержка только systemd
emerge-ai SHALL поддерживать только systemd-системы: рекомендации агента и системные действия SHALL использовать инструменты systemd (systemctl и т.п.) и SHALL не формировать сценарии для openrc. Перед любыми изменениями системы emerge-ai SHALL проверять init и при не-systemd SHALL отказывать без запуска emerge; режимы без изменений системы (план, дайджест новостей, мета-флаги) работают с предупреждением.

#### Scenario: Рекомендация по сервису
- **WHEN** решение требует перезапуска сервиса
- **THEN** агент предлагает действие через systemctl, без упоминания openrc-команд

#### Scenario: Host без systemd
- **WHEN** на OpenRC-хосте выполнено `emerge-ai app-editors/vim`
- **THEN** запуск завершён отказом с указанием, что поддерживаются только systemd-системы; emerge не запускался, система не изменена

#### Scenario: План на не-systemd host
- **WHEN** на OpenRC-хосте выполнено `emerge-ai -pNuDN @world`
- **THEN** показано предупреждение об отсутствии systemd, план сформирован, emerge запущен только в режиме pretend

#### Scenario: Мета-флаги не требуют systemd
- **WHEN** на OpenRC-хосте выполнено `emerge-ai --version`
- **THEN** версия напечатана, код выхода 0
