# Spec Delta

## MODIFIED Requirements

### Requirement: Конфигурационный файл
emerge-ai SHALL читать `/etc/portage/emerge-ai.json` со схемой: эндпоинт и ключ LLM, `language` (default: auto из локали), `show_digest`, `etc_update_after_build`, `changelog_digest`, `agent.web_access` (default: включено). Опция `llm.reasoning_show` из схемы ИСКЛЮЧЕНА: при её наличии в файле emerge-ai SHALL проигнорировать ключ с предупреждением, указывающим на флаг `-v`/`--verbose`. Файл SHALL иметь права 0600 root (хранит API-ключ); при более широких правах emerge-ai SHALL предупреждать.

#### Scenario: Нет эндпоинта
- **WHEN** в конфиге не задан LLM-эндпоинт
- **THEN** emerge-ai отчётливо сообщил об ошибке конфигурации

#### Scenario: Широкие права конфига
- **WHEN** `/etc/portage/emerge-ai.json` доступен на чтение всем
- **THEN** emerge-ai вывел предупреждение о риске утечки ключа

#### Scenario: Удалённый ключ в конфиге
- **WHEN** в конфиге присутствует `reasoning_show`
- **THEN** emerge-ai продолжил работу, проигнорировав ключ, и вывел предупреждение о том, что вывод рассуждений теперь управляется `-v`/`--verbose`

### Requirement: Вывод рассуждений
emerge-ai SHALL выводить рассуждения модели (поле `reasoning` ответа эндпоинта) тогда и только тогда, когда в аргументах команды присутствует emerge-флаг `-v` или `--verbose`, включая кластеры коротких опций (например `-av`); флаг при этом SHALL передаваться emerge без изменений. Без `-v` рассуждения выводиться не SHALL, даже если эндпоинт их возвращает.

#### Scenario: Рассуждения показаны
- **WHEN** выполнено `emerge-ai -av ...` и эндпоинт отдаёт `reasoning_content`
- **THEN** текст рассуждений показан в консоли и emerge получил `-av` без изменений

#### Scenario: По умолчанию скрыты
- **WHEN** выполнено `emerge-ai -a ...` (без `-v`) и эндпоинт отдаёт `reasoning_content`
- **THEN** рассуждения в консоли не показаны, основной вывод не затронут
