# Tasks

## 1. Подготовка

- [ ] 1.1 Удалить порождённые артефакты с записанным старым именем: `rm -rf **/__pycache__ .pytest_cache .mypy_cache .ruff_cache`, затем `pip uninstall -y emerge_ai` (снимает `__editable__.emerge_ai-3.0.82.pth`); проверить: `find . -name __pycache__ -not -path './.venv/*'` пусто и `ls .venv/lib/python*/site-packages | grep -i emerge_ai` пусто
- [ ] 1.2 Зафиксировать снимок «до» для последующей сверки: `git status --porcelain` пуст (чистое дерево), список затронутых файлов сохранён в `/tmp/opencode/rename-before.txt` (`git ls-files | xargs grep -l 'emerge[-_]ai' | grep -v '^openspec/changes/archive/'`) — проверить: в списке 87 файлов и ни одного из `archive/`
- [ ] 1.3 Сделать резервную копию рабочего конфига хоста: `sudo cp -a /etc/portage/emerge-ai.json /root/aimerge-config.bak` — проверить: `sudo test -s /root/aimerge-config.bak` и `sudo stat -c '%a %U' /root/aimerge-config.bak` даёт `600 root`

## 2. Переименование кода

- [ ] 2.1 Переместить каталоги и файлы через `git mv` (до содержательной замены, см. design D3): `src/emerge_ai` → `src/aimerge`, `packaging/app-portage/emerge-ai` → `packaging/app-portage/aimerge`, `emerge-ai-9999.ebuild` → `aimerge-9999.ebuild`, `packaging/emerge-ai.json.default` → `packaging/aimerge.json.default` — проверить: `git status --porcelain` показывает записи `R` (rename), а не пары `D`+`?`
- [ ] 2.2 Заменить `EMERGE_AI_` → `AIMERGE_` (9 имён: `CONFIG`, `PROMPTS_DIR`, `RUNS_DIR`, `TIERS_CACHE`, `RULES`, `EBUILD`, `TEST_MODEL`, `TEST_ENDPOINT`, `TEST_API_KEY`) — проверить: `git grep -n 'EMERGE_AI'` пусто
- [ ] 2.3 Заменить `emerge_ai` → `aimerge` (импорты в 29 модулях и 69 тестах, `pyproject.toml`: `name`, `[project.scripts]`, `attr = aimerge.__version__`) — проверить: `python -c "import aimerge, aimerge.cli, sys; sys.path"` из `src` проходит и `git grep -n 'emerge_ai' -- ':!openspec/changes/archive'` пусто
- [ ] 2.4 Заменить `emerge-ai` → `aimerge` в `src/` (имя команды в `--help`/текстах ошибок, префикс `ui.PREFIX`, строки `compat.py`, `config.py`, `portage_compat.py`) и в `pyproject.toml` — проверить: `git grep -n 'emerge-ai' -- src pyproject.toml` пусто
- [ ] 2.5 Обновить ассерты тестов, сверяющие буквальные строки (`ui.py:54`-префикс в ~30 местах, `test_ui.py:99-101`, `test_cli_integration.py:469`, `test_llm.py:721`) — проверить: `pytest -q -m "not integration"` зелёное
- [ ] 2.6 Проверить неприкосновенность доменной лексики (design «Не трогать»): в диффе нет изменённых строк с `load_emerge_config`, `emerge_config`, `emerge-deselect`, `EMERGE_STUB_`, `emerge_stub`, `emerge_binary`, `emerge_args`, `Emerge` — проверить: `git diff -U0 | grep -E '^[+-].*(load_emerge_config|emerge_config|emerge-deselect|EMERGE_STUB|emerge_stub|emerge_binary)'` пусто

## 3. Поверхность хоста: пути, env, охрана агента, упаковка

- [ ] 3.1 Перевести константы FHS в `src/aimerge/` на новые пути: `config.py:13`, `cli.py:815,817`, `prompts.py:11,14`, `tiers.py:17`, `journal.py:12`, `overlay.py:12`, `changelog.py:122`, `state.py:13`, `rollback.py:18,19`, `gate.py:18` — проверить: `git grep -n '/\(etc/portage\|var/lib\|var/log\|var/cache\|usr/share\|\.snapshots\)/emerge-ai'` пусто и `pytest -q -m "not integration"` зелёное
- [ ] 3.2 Добавить в `opencode.json` зеркало охранных правил на новую команду (design D6): `deny` на `aimerge *` и `sudo aimerge *` c `allow` только для `--version`, `-p`, `--pretend`, `--info` (и `sudo`-вариантов), правила на `emerge *` сохранить; перевести allow-пути `/var/db/repos/emerge-ai-test/**`, `/etc/portage/repos.conf/emerge-ai*`, `rm * /var/db/repos/emerge-ai-test*` на `aimerge` — проверить: запуск мутационного `aimerge sys-apps/foo` отклоняется на уровне разрешения (до portage), `aimerge --version` разрешён
- [ ] 3.3 Обновить ebuild `packaging/app-portage/aimerge/aimerge-9999.ebuild`: `DESCRIPTION`, `HOMEPAGE`, `EGIT_REPO_URI` на `github.com/Sheridan/aimerge`, `insinto /usr/share/aimerge`, `doins aimerge.json.default`, `pkg_postinst` на `/etc/portage/aimerge.json` и `/usr/share/aimerge/aimerge.json.default`, `pkg_postinst`-текст про `aimerge --help` — проверить: `ebuild packaging/app-portage/aimerge/aimerge-9999.ebuild manifest` проходит
- [ ] 3.4 Проверить `packaging/app-portage/aimerge/metadata.xml` и `packaging/aimerge.json.default` на остатки старого имени и совпадение ключей с `config.py` — проверить: `grep -rn 'emerge-ai\|emerge_ai' packaging/` пусто

## 4. Документы и спецификации

- [ ] 4.1 Переименовать в `openspec/specs/**` (15 файлов, 69 требований из 95 содержат имя) — проверить: `grep -rl 'emerge[-_]ai' openspec/specs` пусто, при этом требования по-прежнему говорят об `emerge` там, где речь о Gentoo (`grep -c 'emerge' openspec/specs/cli-compat/spec.md` остаётся содержательным, не нулевым)
- [ ] 4.2 Переименовать в незаархивированных `openspec/changes/**` (14 файлов: `fix-deselect-world-atom`, `consent-question-channel`, `fix-queued-plan-parsing`, `highlight-decisions-and-findings`, `fix-license-channel-filename`, `fix-package-edit-directory-target`), не трогая `openspec/changes/archive/**` — проверить: `git status --porcelain openspec/changes/archive` пусто и `grep -rl 'emerge[-_]ai' openspec/changes --exclude-dir=archive` пусто
- [ ] 4.3 Обновить `README.md` (83 вхождения: заголовок, установка из оверлея, `package.accept_keywords/emerge-ai`, `/etc/portage/emerge-ai.json`, коды выхода), `LIVE_CHECKS.md` (125, включая `/.snapshots/emerge-ai`) и `DECISIONS.md` — проверить: `grep -n 'emerge-ai\|emerge_ai' README.md LIVE_CHECKS.md DECISIONS.md` пусто и записанные в README пути (`app-portage/aimerge`, `/etc/portage/aimerge.json`) дословно совпадают с ebuild из 3.3
- [ ] 4.4 Обновить модель-фейсинг тексты `prompts/rules/00-role.md`, `10-safety.md`, `20-ladder.md` (9 вхождений, включая `/var/lib/emerge-ai/overlay`) — проверить: `grep -rn 'emerge-ai' prompts/` пусто и тесты, проверяющие текст промптов (`test_prompts.py`, `test_injection.py`), зелёные
- [ ] 4.5 Проверить полноту и валидность: `git grep -n 'emerge[-_]ai' -- ':!openspec/changes/archive'` пусто и `openspec validate rename-project-to-aimerge --strict` проходит

## 5. Живой хост разработки

- [ ] 5.1 Удалить установленный старый пакет: `sudo emerge --unmerge app-portage/emerge-ai` — проверить: `which -a emerge-ai` пусто, `/var/db/pkg/app-portage/emerge-ai-9999` отсутствует
- [ ] 5.2 Перенести состояние `mv`-ом (не `cp`, см. design D5): конфиг `/etc/portage/emerge-ai.json` → `/etc/portage/aimerge.json`, `/var/lib/emerge-ai` → `/var/lib/aimerge`, `/var/log/emerge-ai` → `/var/log/aimerge`, `/var/cache/emerge-ai` → `/var/cache/aimerge` — проверить: `sudo stat -c '%a %U' /etc/portage/aimerge.json` = `600 root`, `sudo grep -o '"model"[^,]*' /etc/portage/aimerge.json` непустой, файлы аудита на месте
- [ ] 5.3 Перенести тестовую инфраструктуру оверлеев: `/var/db/repos/emerge-ai-test` → `/var/db/repos/aimerge-test` и записи `location`/секций в `/etc/portage/repos.conf/emerge-ai-test.conf`, `emerge-ai-test-base.conf` (имена файлов и секций → `aimerge-test{,-base}`) — проверить: `sudo portageq repos_config /` показывает только `aimerge-test`/`aimerge-test-base` и ни одной записи `emerge-ai`
- [ ] 5.4 Обновить личный оверлей: `babylon_5/app-portage/emerge-ai/` → `babylon_5/app-portage/aimerge/`, ebuild и `metadata.xml` из 3.3, пересоздать `Manifest`; затем `sudo emerge --ask app-portage/aimerge` — проверить: `/var/db/pkg/app-portage/aimerge-9999` и `/usr/bin/aimerge` существуют, `which -a emerge-ai` по-прежнему пусто
- [ ] 5.5 Восстановить dev-окружение: `pip install -e .` в репозитории — проверить: `pip show aimerge` печатает `Name: aimerge`, `python -c "from aimerge import cli"` проходит, `pytest -q -m "not integration"` зелёное

## 6. Внешние ссылки и интеграционная проверка

- [ ] 6.1 Переименовать репозиторий и локальный remote: `gh repo rename aimerge --repo Sheridan/emerge-ai --yes`, затем `git remote set-url origin git@github.com:Sheridan/aimerge.git` — проверить: `gh repo view --json name -q .name` = `aimerge` и `git ls-remote origin HEAD` проходит на новом URL
- [ ] 6.2 Смоук read-only поверхностей: `aimerge --version`, `aimerge --help`, `aimerge -p sys-apps/baselayout` — проверить: rc `0`, префикс строк `aimerge: ` (не `emerge-ai: `), в выводе `--help` список собственных флагов начинается с `aimerge own flags`, живой `emerge` не запущен с мутацией
- [ ] 6.3 Смоук состояния: `aimerge -p`-прогон и `aimerge --changelog` — проверить: новый run-каталог появился в `/var/lib/aimerge/runs`, запись в `/var/log/aimerge/journal.jsonl` использует имя `aimerge`, `--changelog` не падает на пустом `gh_repos`
- [ ] 6.4 Итоговая проверка чистоты переименования: `git show --stat HEAD` для коммита переименования — только переименование, без попутных изменений логики; `git grep -c 'emerge[-_]ai' -- ':!openspec/changes/archive'` пусто; `pytest -q -m "not integration"` зелёное
- [ ] 6.5 Переименовать рабочий каталог `~/development/emerge-ai` → `~/development/aimerge` и обновить ссылки в сессии/редакторе — проверить: `git -C ~/development/aimerge status` работает, `openspec list --json` читает корень по новому пути

## Workflow follow-up

- Заархивировать change после ревью (`openspec archive rename-project-to-aimerge`); в `archive/` он осядет уже с новым именем, поэтому в архиве сосуществуют оба написания — это принято в design «Open Questions».
- После архивации проверить, что `openspec/specs/**` не содержат `emerge-ai`, а `emerge` как доменный термин остался.
