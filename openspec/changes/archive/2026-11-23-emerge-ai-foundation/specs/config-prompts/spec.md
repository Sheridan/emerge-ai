# Spec Delta

## Purpose

Централизованная конфигурация emerge-ai с дефолтами, OpenAI-совместимый интерфейс LLM с native tool-calling и раскладка промптов-правил, обязательных для исполнения агентом.

## ADDED Requirements

### Requirement: Конфигурационный файл
emerge-ai SHALL читать `/etc/portage/emerge-ai.json` со схемой: эндпоинт и ключ LLM, `llm.reasoning_show` (default: включено), `language` (default: auto из локали), `show_digest`, `etc_update_after_build`, `changelog_digest`, `agent.web_access` (default: включено). Файл SHALL иметь права 0600 root (хранит API-ключ); при более широких правах emerge-ai SHALL предупреждать.

#### Scenario: Нет эндпоинта
- **WHEN** в конфиге не задан LLM-эндпоинт
- **THEN** emerge-ai отчётливо сообщил об ошибке конфигурации

#### Scenario: Широкие права конфига
- **WHEN** `/etc/portage/emerge-ai.json` доступен на чтение всем
- **THEN** emerge-ai вывел предупреждение о риске утечки ключа

### Requirement: OpenAI-совместимый интерфейс с tool calling
Агент SHALL общаться с эндпоинтом через OpenAI-совместимый `/v1/chat/completions` в режиме native tool-calling; поддержка локальных и облачных эндпоинтов одинакова.

#### Scenario: Tool call
- **WHEN** модель вернула `tool_calls`
- **THEN** emerge-ai исполнил инструмент (в sandbox) и продолжил диалог с результатом

### Requirement: Вывод рассуждений
При включённом `llm.reasoning_show` emerge-ai SHALL выводить рассуждения модели, если эндпоинт возвращает reasoning-поле; при выключенном — не выводить.

#### Scenario: Рассуждения показаны
- **WHEN** `llm.reasoning_show` включён и эндпоинт отдаёт `reasoning_content`
- **THEN** текст рассуждений показан в консоли

### Requirement: Язык ответов
Язык ответов LLM пользователю SHALL браться из `language`; значение `auto` SHALL определяться из локали пользователя; настройка SHALL переопределять auto.

#### Scenario: Auto-язык
- **WHEN** `language: auto` и LANG=`ru_RU.UTF-8`
- **THEN** ответы агента на русском

### Requirement: Раскладка промптов
Все промпты и правила, обязательные к исполнению, SHALL храниться в `/usr/share/emerge-ai/prompts`; сгенерированные системно-зависимые промпты SHALL храниться в `/var/lib/emerge-ai/prompts`; агент SHALL строго соблюдать правила из обеих директорий.

#### Scenario: Правила соблюдены
- **WHEN** правила запрещают системные изменения вне consent gate
- **THEN** агент не выполняет такие изменения ни в одном режиме сбора информации
