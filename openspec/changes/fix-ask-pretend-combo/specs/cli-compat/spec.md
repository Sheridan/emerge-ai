# Spec Delta

## ADDED Requirements

### Requirement: Доминирование --pretend над --ask
При одновременном наличии `--pretend` (включая `-p` и кластеры вида `-ap`) и `--ask`/`--ask-forever` emerge-ai SHALL отработать только фазу плана: штатный pretend-вывод emerge с обогащением, без вопроса о продолжении, и SHALL NOT запускать merge-прогон; код выхода — код выхода pretend-прогона. Merge-прогон не запускается ни при каком ответе оператора.

#### Scenario: Связка -a -p не устанавливает
- **WHEN** выполнено `emerge-ai -a -p app-editors/vim` и оператор готов ответить «y» на любой вопрос
- **THEN** показан pretend-вывод с обогащением, вопрос «Proceed?» не задан, merge не запускался, код выхода — код pretend-прогона

#### Scenario: Кластер -ap
- **WHEN** выполнено `emerge-ai -ap app-editors/vim`
- **THEN** запуск ведёт себя как `-a -p`: только фаза плана, без вопроса и без merge

#### Scenario: -a без -p подтверждает и устанавливает
- **WHEN** выполнено `emerge-ai -a app-editors/vim` (без `--pretend`) и оператор ответил «y»
- **THEN** после обогащённого плана задан вопрос «Proceed?» и по «y» выполнен merge-прогон (прежнее поведение)
