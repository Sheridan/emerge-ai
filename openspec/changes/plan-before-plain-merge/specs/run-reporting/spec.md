# Spec Delta

## MODIFIED Requirements

### Requirement: Автоматический doctor
При сборке world/system или массовом world-апдейте emerge-ai SHALL автоматически выполнить preflight: dry-run резолвера, риск-тирование merge-листа, предупреждения о критичных пакетах и суммарную оценку времени; preflight выполняется в любом режиме запуска — включая обычный запуск без `--pretend`/`--ask`, до начала слияний; отдельной командой doctor не является. Информационные блоки preflight SHALL NOT попадать в stdout мутационного прогона — в stdout остаётся только вывод emerge.

#### Scenario: Док на world
- **WHEN** запущен `emerge-ai -uDN @world` с пакетом tier 1 в плане
- **THEN** до начала слияний показан doctor-отчёт с предупреждением о tier 1

#### Scenario: Обычный запуск без флагов
- **WHEN** запущен `emerge-ai -uDN @world` без `--pretend`/`--ask`
- **THEN** doctor-отчёт показан до подтверждения и начала merge, stdout содержит только вывод emerge

#### Scenario: Одиночный rest-tier пакет
- **WHEN** запущен `emerge-ai app-editors/vim`
- **THEN** doctor-отчёт не показывается
