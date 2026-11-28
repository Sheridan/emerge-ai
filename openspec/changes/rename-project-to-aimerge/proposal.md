# Proposal

## Why

Проект называется `emerge-ai`, но `emerge` — это ещё и доменная лексика: бинарь
Gentoo, API portage, имена аргументов. Из-за совпадения имени с предметной областью
любая работа с кодом требует каждый раз различать «это имя проекта» и «это про
portage»: в репозитории ~1400 вхождений `emerge` относятся к Gentoo
(`emerge_binary`, `emerge_stub`, `emerge_args`, `EMERGE_STUB_*`,
`portage.actions.load_emerge_config`, `emerge-deselect`) и ~1550 — к имени проекта.
Новое имя `aimerge` так не неоднозначно: оно не содержит `emerge` как подстроку,
не конфликтует с `/usr/bin/emerge` и читается как «AI + merge», то есть смысл
сохраняется.

Пользователей нет, утилита в разработке, поэтому переименование делается
решительно: без fallback-чтения старых путей, без алиасов старых env-переменных и
без обратной совместимости форматов.

## What Changes

- **BREAKING** Python-пакет `emerge_ai` → `aimerge`: каталог `src/emerge_ai/` →
  `src/aimerge/`, все импорты (29 модулей, 69 тестовых файлов),
  `pyproject.toml` (`name`, `[project.scripts]`, `attr = aimerge.__version__`).
- **BREAKING** Имя запускаемой команды `emerge-ai` → `aimerge` (console script,
  префикс строк вывода `emerge-ai: ` → `aimerge: `, тексты `--help`, коды выхода
  в документации).
- **BREAKING** Env-переменные `EMERGE_AI_*` → `AIMERGE_*` (9 имён: `CONFIG`,
  `PROMPTS_DIR`, `RUNS_DIR`, `TIERS_CACHE`, `RULES`, `EBUILD`, `TEST_MODEL`,
  `TEST_ENDPOINT`, `TEST_API_KEY`) — старые не читаются.
- **BREAKING** Пути FHS: `/etc/portage/emerge-ai.json` → `/etc/portage/aimerge.json`,
  `/usr/share/emerge-ai/` → `/usr/share/aimerge/`, `/var/lib/emerge-ai/` →
  `/var/lib/aimerge/`, `/var/log/emerge-ai/` → `/var/log/aimerge/`,
  `/var/cache/emerge-ai/` → `/var/cache/aimerge/`, `/.snapshots/emerge-ai/` →
  `/.snapshots/aimerge/`. Тестовые оверлеи `emerge-ai-test{,-base}` →
  `aimerge-test{,-base}` (включая записи в `/etc/portage/repos.conf/`).
- Ebuild: `app-portage/emerge-ai/emerge-ai-9999.ebuild` →
  `app-portage/aimerge/aimerge-9999.ebuild`, `emerge-ai.json.default` →
  `aimerge.json.default`; категория остаётся `app-portage` (инструмент про portage,
  а не про «AI вообще»). `HOMEPAGE`/`EGIT_REPO_URI` → `github.com/Sheridan/aimerge`.
- Репозиторий: `github.com/Sheridan/emerge-ai` → `Sheridan/aimerge` (gh CLI
  доступен, авторизация подтверждена), `origin` в `.git/config`, рабочий каталог
  `~/development/emerge-ai` → `~/development/aimerge`.
- `openspec/specs/**` и незаархивированные `openspec/changes/**` — имя меняется в
  формулировках (69 требований из 95 содержат старое имя), чтобы агент при чтении
  спецификаций не встречал несуществующую команду.
- **Не меняется:** история git (120 коммитов, тегов нет — переименование только
  вперёд, `git log` сохраняет старое имя); `openspec/changes/archive/**`
  (115 файлов — исторический журнал, та же логика, что с историей коммитов);
  доменная лексика Gentoo/portage (см. design.md); поведение и коды выхода.

## Capabilities

### New Capabilities

нет.

### Modified Capabilities

нет — поведение не меняется ни в одном из 69 требований, меняется только
идентификатор в их формулировках. Change помечен `skip_specs: true`; спецификации
обновляются прямым текстовым переименованием `openspec/specs/**` в рамках этого
change (контроль — `grep` даёт ноль вхождений вне `archive/`), без дельта-файлов:
15 дельта-спеков означали бы 69 переписанных целиком требований со сценариями, то
есть 69 точек расхождения с реальным текстом при нулевой change в поведении.

## Impact

- Код: 108 текстовых файлов (32 `src/`, 34 `tests/`, 32 `openspec/` live — 15 спеков и
  17 файлов незаархивированных change, `pyproject.toml`, `opencode.json`, `README.md`,
  `LIVE_CHECKS.md`, `DECISIONS.md`, 3 файла `prompts/rules/`, 2 файла `packaging/`
  плюс `packaging/aimerge.json.default`) плюс два переименовываемых каталога.
  Проверено `git ls-files` по шаблону `emerge[-_]ai`: 111 вхождений-файлов, из них
  3 — артефакты этого change, они старое имя сохраняют сознательно.
- Модель-фейсинг: `prompts/rules/00-role.md` («You are the repair agent inside
  emerge-ai») и `10-safety.md`/`20-ladder.md` (`/var/lib/emerge-ai/overlay`) —
  9 вхождений, меняются как имя проекта; `emerge-deselect` (имя action в
  consent-канале) не трогается.
- Живой хост разработки: установлен `app-portage/emerge-ai-9999`
  (`/usr/bin/emerge-ai`), копия в личном оверлее `babylon_5/app-portage/emerge-ai/`
  с `Manifest`, рабочий `/etc/portage/emerge-ai.json` (0600, содержит API-ключ),
  `/var/lib/emerge-ai/` (`runs/`, `tiers.json`, `audit.journal.jsonl`) и
  `/var/log/emerge-ai/` (`journal.jsonl`, `decisions.log`). Всё это нужно
  перенести/пересобрать, права `0600` и владельца root сохранить.
- `.venv`: editable-установка `__editable__.emerge_ai-3.0.82.pth` после
  переименования каталога становится битой — требуется `pip install -e .` заново;
  `__pycache__`/`.pytest_cache`/`.mypy_cache` содержат старые строки и удаляются,
  а не правятся.
- Не затрагивается: `changelog`-фича ходит в GitHub API по `repo` из конфига
  (`gh_repos`, по умолчанию `[]`) — захардкоженного `Sheridan/emerge-ai` в `src/`
  нет, переименование репозитория её не ломает. CI в репозитории нет.
