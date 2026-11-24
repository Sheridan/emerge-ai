# Proposal

## Why

Схема конфига в спецификации (`config-prompts`, «Конфигурационный файл», `openspec/specs/config-prompts/spec.md:9`)
задаёт ключи `show_digest`, `etc_update_after_build`, `changelog_digest` и вложенный
`agent.web_access`, но код живёт в параллельной вселенной: dataclass `Config` содержит плоские
`web_access`, `etc_update_llm`, `post_run_digest` (`src/emerge_ai/config.py:41-46`), ключа
`changelog_digest` нет вовсе, а `from_dict` берёт только пересечение с `DEFAULTS` и печатает
`ignoring unknown key` для остального (`config.py:59-61`). Итог (REVIEW_NOTES M10): конфиг,
написанный строго по спецификации, деградирует — флаги молча не работают, а README
(`README.md:81-88,93` — пример с плоским `web_access`; `:163-164` — `post_run_digest`)
документирует имена кода, а не спецификации.

## What Changes

- `Config` переходит на канонические имена: `show_digest`, `etc_update_after_build`,
  `changelog_digest` (новый, default `true`), вложенный `agent: {"web_access": true}`
  (атрибут данных `web_access` сохраняется, меняется только разбор файла).
- Старые имена файла (`post_run_digest`, `etc_update_llm`, плоский `web_access`) читаются как
  алиасы с предупреждением `... is deprecated, use ...`; при конфликте старого и нового имени
  побеждает новое; `_REMOVED_KEYS` (`reasoning_show`) остаётся отдельным механизмом.
- Потребители (`cli.py:161,173,234`) переходят на новые атрибуты.
- README: JSON-пример и список ключей приводятся к канонической схеме, секция «Дайджесты» —
  к `show_digest`/`changelog_digest`; шаблон `packaging/emerge-ai.json.default` дополняется
  каноническими ключами (правило прав 0600 не меняется — меняется только содержимое).

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `config-prompts`: добавлено требование «Алиасы устаревших ключей конфига» — канонические
  имена обязательны для реализации, устаревшие читаются как алиасы с предупреждением,
  каноническое имя имеет приоритет, флаги дайджестов по умолчанию включены.

## Impact

- **Код**: `src/emerge_ai/config.py` (`Config`, `DEFAULTS`, `from_dict` + таблица алиасов),
  `src/emerge_ai/cli.py:161,173,234`.
- **Тесты**: `tests/test_config.py` (алиасы/конфликты/`changelog_digest`; `:10` — проверка
  `cfg.web_access is True` сохраняется), smoke-тесты CLI с новыми ключами.
- **Docs/пакет**: `README.md` (конфиг, дайджесты), `packaging/emerge-ai.json.default`.
- **Зависимость**: потребитель `changelog_digest` появится в отдельном change
  `auto-changelog-digest` (REVIEW_NOTES M11) — здесь ключ только парсится и хранится, что
  безвредно (совпадение с default-поведением: changelog и так печатается по запросу).
