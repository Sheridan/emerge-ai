# Tasks

## 1. Канонические ключи в Config

- [ ] 1.1 В `src/emerge_ai/config.py` переименовать поля dataclass и `DEFAULTS`:
      `post_run_digest`→`show_digest`, `etc_update_llm`→`etc_update_after_build`,
      добавить `changelog_digest: True`; `web_access` оставить плоским атрибутом (default `True`)
- [ ] 1.2 В `from_dict` (`config.py:58-68`) до фильтрации по `DEFAULTS` нормализовать вход по
      таблице `_ALIASES = {"post_run_digest": "show_digest", "etc_update_llm":
      "etc_update_after_build", "web_access": "web_access" (из плоского), "agent": →
      вложенный web_access}`: сработавший алиас → `warn("config: key '<old>' is deprecated,
      use '<new>'")`; при заданных обоих именах — значение канона, алиас игнорируется с
      предупреждением; невалидный `agent` (не объект) → предупреждение + дефолт
- [ ] 1.3 Убедиться, что `_REMOVED_KEYS` (`reasoning_show`) разбирать независимо от алиасов и
      канонический набор не печатает «unknown key» для `agent`

## 2. Потребители

- [ ] 2.1 В `src/emerge_ai/cli.py` обновить чтения: `:161` и `:173` (`cfg.etc_update_llm` →
      `cfg.etc_update_after_build`), `:234` (`cfg.post_run_digest` → `cfg.show_digest`);
      grep `etc_update_llm\|post_run_digest` по `src/` — ноль вхождений

## 3. Тесты

- [ ] 3.1 `tests/test_config.py`: канонический конфиг (`show_digest:false`,
      `etc_update_after_build:false`, `changelog_digest:false`,
      `agent:{"web_access":false}`) → значения применены, предупреждений нет
- [ ] 3.2 Алиасы: старый `post_run_digest:false` → `cfg.show_digest is False` + предупреждение
      с `show_digest`; то же для `etc_update_llm` и плоского `web_access`
- [ ] 3.3 Конфликт `etc_update_after_build:false` + `etc_update_llm:true` → False +
      предупреждение; `tests/test_config.py:10` (`cfg.web_access is True` на пустом конфиге)
      проходит
- [ ] 3.4 Обновить все конфиг-ключи в `tests/test_cli.py`/`tests/test_etcupdate.py` на канон;
      прогнать `pytest` целиком

## 4. Docs и packaging

- [ ] 4.1 `packaging/emerge-ai.json.default`: добавить `show_digest`,
      `etc_update_after_build`, `changelog_digest`, `"agent": {"web_access": true}`
      (содержимое; путь/права правила не меняются)
- [ ] 4.2 README: JSON-пример (`:81-88`) и расшифровка ключей (`:90-97`) — канонические имена
      + `changelog_digest`; секция «Дайджесты» (`:163-164`) — `show_digest`,
      `changelog_digest` вместо `post_run_digest`; grep `post_run_digest\|etc_update_llm` по
      README — ноль вхождений
- [ ] 4.3 `openspec validate align-config-schema` проходит без ошибок
