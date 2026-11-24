# Proposal

## Why

Спек `cli-compat` «Поддержка только systemd» (openspec/specs/cli-compat/spec.md:75-80) требует поддержки только systemd и отказа от openrc-сценариев, но в коде проверка init-системы отсутствует полностью: init определяется лишь как контекст промпта через `/proc/1/comm` (`src/emerge_ai/prompts.py:71`), при недоступности — «unknown» (замечание M9, REVIEW_NOTES.md:145-154). На OpenRC-машине emerge-ai сейчас честно «ставит» пакеты, а потом агент слеп: в sandbox-allowlist есть `journalctl` (`src/emerge_ai/sandbox.py:18,117`), аналога `rc-service`/`rc-log` нет, рекомендации сервиса могут противоречить фактическому init. Решение пользователя зафиксировано: спека «только systemd» остаётся, доводится код (полумеры из M9 закрываются в сторону спека, а не обратно).

## What Changes

- Появляется проверка init-системы до любых мутационных прогонов emerge: не-systemd — явный отказ с диагностикой и понятным кодом выхода, emerge не запускается ни разу.
- Read-only режимы (`--pretend`, `--changelog`, `--version`/`--help`) не требуют systemd: предупреждение и обычная работа (совместимость с CI/контейнерами).
- Промпты правил и README приводят терминологию к systemd-only: рекомендации сервисов — только `systemctl`/`journalctl`; `journalctl` остаётся в sandbox-allowlist, openrc-эквиваленты (`rc-service`, `rc-log`) не добавляем.
- Таблица tier-hints не меняется: `sys-apps/openrc: 1` (`src/emerge_ai/tiers.py:25`) — это критичность пакета при сборке, а не рекомендация по управлению сервисом.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `cli-compat`: «Поддержка только systemd» — к нормативу про рекомендации добавляется норматививная достижимость проверки: init проверяется до мутаций, не-systemd даёт явный отказ, read-only режимы работают с предупреждением. Базовый сценарий про systemctl сохраняется.

## Impact

- `src/emerge_ai/cli.py` — гейт в начале мутационного пути (рядом с гейтом совместимости portage, `cli.py:42-50`) + предупреждение в read-only.
- Новый модуль `src/emerge_ai/init_check.py` — детект systemd (канонический признак `/run/systemd/system`, fallback `/proc/1/comm`) с инъективной точкой для тестов (стиль `btrfs_fn`/`run_fn`).
- `prompts/rules/00-role.md` / `10-safety.md` — явная директива «только systemctl/journalctl, openrc не предлагать»; `README.md` — секция поддерживаемых систем.
- `tests/test_init_check.py`, CLI-тесты (`test_cli.py`): отказ/предупреждение/rc.
- Пересечения: `plan-before-plain-merge` (общий pre-merge блок — место вставки гейта) и `wire-rollback-channel` (режим `--rollback` — предупреждение вместо отказа).
