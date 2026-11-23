# Proposal

## Why

emerge-ai сегодня устанавливается только «из checkout» (pytest pythonpath, относительный
путь `prompts/`), тогда как проект по своей природе — системная обёртка Gentoo: пользователю
нужен штатный путь установки через portage. Требуется ebuild для личного оверлея, ставящий
пакет целиком (CLI, prompt-правила, метаданные зависимостей).

## What Changes

- Новый live-ebuild `app-portage/emerge-ai/emerge-ai-9999.ebuild` (git-r3, HTTPS-URL
  публичного репозитория GitHub, EAPI 8, distutils-r1), хранимый в репозитории под
  `packaging/app-portage/emerge-ai/` как единый источник для личных оверлеев пользователей.
- ebuild ставит prompt-правила из `prompts/` в `/usr/share/emerge-ai/prompts` — раскладку,
  которую уже требует существующий spec `config-prompts` («Раскладка промптов»), но которую
  код сейчас не обеспечивает: `rules_dir()` знает только про `EMERGE_AI_PROMPTS_DIR` и
  относительный `./prompts` от CWD.
- Малая правка `emerge_ai.prompts.rules_dir()`: порядок разрешения
  env → `./prompts` (dev-checkout) → `/usr/share/emerge-ai/prompts` (installed).
  Обратная совместимость с dev-раскладкой сохраняется.
- Инструктаж в README: как подключить ebuild в личный оверлей (без создания оверлей-инфраструктуры
  в этом репозитории), accept_keywords, права конфига, опциональные рантайм-инструменты.

## Capabilities

### New Capabilities
- `gentoo-packaging`: установка emerge-ai из ebuild на Gentoo — содержимое пакета, рантайм-зависимости,
  размещение prompt-правил, изоляция build-фазы от живого хоста, postinst-инструктаж.

### Modified Capabilities
<!-- нет: раскладка /usr/share/emerge-ai/prompts уже нормативна в config-prompts; правка кода
     приводит реализацию в соответствие, текст requirements не меняется -->

## Impact

- `src/emerge_ai/prompts.py` — разрешение директории правил (fallback на install-путь);
  затронутые юнит-тесты `tests/`.
- Новый файл `packaging/app-portage/emerge-ai/emerge-ai-9999.ebuild`; секция установки в `README.md`.
- RDEPEND: `sys-apps/portage` (бинарь emerge + importable модуль portage), `sys-apps/util-linux`
  (findmnt); опционально через postinst: `sys-fs/btrfs-progs`, `app-portage/genlop`, `dev-vcs/git`.
- Код ядра emerge-ai (агент, тирование, rollback) не меняется; поведение CLI не меняется.
- Риски: HTTPS-доступ к github.com/Sheridan/emerge-ai (репозиторий публичен, проверено HTTP 200);
  live-ebuild требует `~arch`-приёмки пользователем; `import portage` должен резолвиться тем же
  PYTHON-ABI, что и у установленного portage (в ebuild — single-impl).
