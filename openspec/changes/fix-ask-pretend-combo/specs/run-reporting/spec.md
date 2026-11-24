# Spec Delta

## MODIFIED Requirements

### Requirement: Enrich для pretend/ask
При флагах `--pretend`/`--ask` emerge-ai SHALL напечатать штатный вывод emerge без изменений, после чего добавить обогащение от LLM: оценку времени сборки через genlop и краткий дайджест грядущих изменений; финальный вопрос о продолжении SHALL задавать emerge-ai только при наличии `--ask` без `--pretend` — при активном pretend вопрос не задаётся и продолжение не происходит.

#### Scenario: Претенд с оценкой
- **WHEN** выполнено `emerge-ai -p sys-devel/gcc`
- **THEN** после списка emerge показаны оценка времени и дайджест изменений

#### Scenario: Ask с подтверждением
- **WHEN** выполнено `emerge-ai -a @world`
- **THEN** после вывода emerge с обогащением emerge-ai задал вопрос «Proceed?», при «y» установка продолжилась

#### Scenario: Ask с pretend не спрашивает
- **WHEN** выполнено `emerge-ai -a -p @world`
- **THEN** показан обогащённый pretend-вывод, вопрос не задан, install-прогон не выполнялся
