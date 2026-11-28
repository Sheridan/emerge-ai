# Tasks

## 1. Подготовка

- [x] 1.1 Удалить порождённые артефакты с записанным старым именем: `rm -rf **/__pycache__ .pytest_cache .mypy_cache .ruff_cache`, затем `pip uninstall -y emerge_ai` (снимает `__editable__.emerge_ai-3.0.82.pth`); проверить: `find . -name __pycache__ -not -path './.venv/*'` пусто и `ls .venv/lib/python*/site-packages | grep -i emerge_ai` пусто
- [x] 1.2 Зафиксировать снимок «до» для последующей сверки: `git status --porcelain` пуст (чистое дерево), список затронутых файлов сохранён в `/tmp/opencode/rename-before.txt` (`git ls-files | xargs grep -l 'emerge[-_]ai' | grep -v '^openspec/changes/archive/' | grep -v '^openspec/changes/rename-project-to-aimerge/'`) — проверить: в списке 108 файлов (src 32, tests 34, openspec live 32, prompts 3, packaging 2, корневые 5), ни одного из `archive/` и ни одного из каталога этого change
- [x] 1.3 Сделать резервную копию рабочего конфига хоста: `sudo cp -a /etc/portage/emerge-ai.json /root/aimerge-config.bak` — проверить: `sudo test -s /root/aimerge-config.bak` и `sudo stat -c '%a %U' /root/aimerge-config.bak` даёт `600 root`

## 2. Переименование кода

- [x] 2.1 Переместить каталоги и файлы через `git mv` (до содержательной замены, см. design D3): `src/emerge_ai` → `src/aimerge`, `packaging/app-portage/emerge-ai` → `packaging/app-portage/aimerge`, `emerge-ai-9999.ebuild` → `aimerge-9999.ebuild`, `packaging/emerge-ai.json.default` → `packaging/aimerge.json.default` — проверить: `git status --porcelain` показывает записи `R` (rename), а не пары `D`+`?`
- [x] 2.2 Заменить `EMERGE_AI_` → `AIMERGE_` (9 имён: `CONFIG`, `PROMPTS_DIR`, `RUNS_DIR`, `TIERS_CACHE`, `RULES`, `EBUILD`, `TEST_MODEL`, `TEST_ENDPOINT`, `TEST_API_KEY`) — проверить: `git grep -n 'EMERGE_AI'` пусто
- [x] 2.3 Заменить `emerge_ai` → `aimerge` (импорты в 29 модулях и 69 тестах, `pyproject.toml`: `name`, `[project.scripts]`, `attr = aimerge.__version__`) — проверить: `python -c "import aimerge, aimerge.cli, sys; sys.path"` из `src` проходит и `git grep -n 'emerge_ai' -- ':!openspec/changes/archive'` пусто
- [x] 2.4 Заменить `emerge-ai` → `aimerge` в `src/` (имя команды в `--help`/текстах ошибок, префикс `ui.PREFIX`, строки `compat.py`, `config.py`, `portage_compat.py`) и в `pyproject.toml` — проверить: `git grep -n 'emerge-ai' -- src pyproject.toml` пусто
- [x] 2.5 Обновить ассерты тестов, сверяющие буквальные строки (`ui.py:54`-префикс в ~30 местах, `test_ui.py:99-101`, `test_llm.py:721`) — проверить: `pytest -q -m "not integration"` зелёное. **Проверка не выполнена целиком: 613 passed, 1 failed.** Падающий — `test_honest_seam_queue_matches_live_resolve`; он падает одинаково на отдельном worktree с деревом до переименования и на текущем, поэтому к переименованию отношения не имеет, но зелёным прогон называть нельзя. Причина — живое разрешение `@world` с неразрешённым block `!<dev-util/gdbus-codegen-2.88.4`; механизм, по которому он проникает в очередь, разобран в follow-up (это реальный дефект `queued_cpvs`, а не шум окружения). Строки ассертов при этом переведены на новый префикс полностью — сам предмет задачи закрыт
- [x] 2.6 Проверить неприкосновенность доменной лексики (design «Не трогать»): в диффе нет изменённых строк с `load_emerge_config`, `emerge_config`, `emerge-deselect`, `EMERGE_STUB_`, `emerge_stub`, `emerge_binary`, `emerge_args`, `Emerge` — проверить: `git diff -U0 | grep -E '^[+-].*(load_emerge_config|emerge_config|emerge-deselect|EMERGE_STUB|emerge_stub|emerge_binary)'` пусто

## 3. Поверхность хоста: пути, env, охрана агента, упаковка

- [x] 3.1 Перевести константы FHS в `src/aimerge/` на новые пути: `config.py:13`, `cli.py:815,817`, `prompts.py:11,14`, `tiers.py:17`, `journal.py:12`, `overlay.py:12`, `changelog.py:122`, `state.py:13`, `rollback.py:18,19`, `gate.py:18` — проверить: `git grep -n '/\(etc/portage\|var/lib\|var/log\|var/cache\|usr/share\|\.snapshots\)/emerge-ai'` пусто (подтверждено) и `pytest -q -m "not integration"` зелёное (кроме падающего seam-теста из 2.5 — он красный и до переименования)
- [x] 3.2 Добавить в `opencode.json` зеркало охранных правил на новую команду (design D6): `deny` на `aimerge *` и `sudo aimerge *` c `allow` только для `--version`, `-p`, `--pretend`, `--info` (и `sudo`-вариантов), правила на `emerge *` сохранить; перевести allow-пути `/var/db/repos/emerge-ai-test/**`, `/etc/portage/repos.conf/emerge-ai*`, `rm * /var/db/repos/emerge-ai-test*` на `aimerge` — проверить: запуск мутационного `aimerge sys-apps/foo` отклоняется на уровне разрешения (до portage), `aimerge --version` разрешён
- [x] 3.3 Обновить ebuild `packaging/app-portage/aimerge/aimerge-9999.ebuild`: `DESCRIPTION`, `HOMEPAGE`, `EGIT_REPO_URI` на `github.com/Sheridan/aimerge`, `insinto /usr/share/aimerge`, `doins aimerge.json.default`, `pkg_postinst` на `/etc/portage/aimerge.json` и `/usr/share/aimerge/aimerge.json.default`, `pkg_postinst`-текст про `aimerge --help` — проверить: `ebuild packaging/app-portage/aimerge/aimerge-9999.ebuild manifest` проходит
- [x] 3.4 Проверить `packaging/app-portage/aimerge/metadata.xml` и `packaging/aimerge.json.default` на остатки старого имени и совпадение ключей с `config.py` — проверить: `grep -rn 'emerge-ai\|emerge_ai' packaging/` пусто

## 4. Документы и спецификации

- [x] 4.1 Переименовать в `openspec/specs/**` (15 файлов, 69 требований из 95 содержат имя) — проверить: `grep -rl 'emerge[-_]ai' openspec/specs` пусто, при этом требования по-прежнему говорят об `emerge` там, где речь о Gentoo (`grep -c 'emerge' openspec/specs/cli-compat/spec.md` остаётся содержательным, не нулевым)
- [x] 4.2 Переименовать в незаархивированных `openspec/changes/**` (14 файлов: `fix-deselect-world-atom`, `consent-question-channel`, `fix-queued-plan-parsing`, `highlight-decisions-and-findings`, `fix-license-channel-filename`, `fix-package-edit-directory-target`), не трогая `openspec/changes/archive/**` — проверить: `git status --porcelain openspec/changes/archive` пусто и `grep -rl 'emerge[-_]ai' openspec/changes --exclude-dir=archive` пусто
- [x] 4.3 Обновить `README.md` (83 вхождения: заголовок, установка из оверлея, `package.accept_keywords/emerge-ai`, `/etc/portage/emerge-ai.json`, коды выхода), `LIVE_CHECKS.md` (125, включая `/.snapshots/emerge-ai`) и `DECISIONS.md` — проверить: `grep -n 'emerge-ai\|emerge_ai' README.md LIVE_CHECKS.md DECISIONS.md` пусто и записанные в README пути (`app-portage/aimerge`, `/etc/portage/aimerge.json`) дословно совпадают с ebuild из 3.3
- [x] 4.4 Обновить модель-фейсинг тексты `prompts/rules/00-role.md`, `10-safety.md`, `20-ladder.md` (9 вхождений, включая `/var/lib/emerge-ai/overlay`) — проверить: `grep -rn 'emerge-ai' prompts/` пусто и тесты, проверяющие текст промптов (`test_prompts.py`, `test_injection.py`), зелёные
- [x] 4.5 Проверить полноту и валидность: `git grep -n 'emerge[-_]ai' -- ':!openspec/changes/archive' ':!openspec/changes/rename-project-to-aimerge'` пусто и `openspec validate rename-project-to-aimerge --strict` проходит

## 5. Живой хост разработки

- [x] 5.1 Удалить установленный старый пакет: `sudo emerge --unmerge app-portage/emerge-ai` (выполняет пользователь — мутации живого portage вне guard'а агента) — проверить: `which -a emerge-ai` пусто, `/var/db/pkg/app-portage/emerge-ai-9999` отсутствует
- [x] 5.2 Перенести состояние `mv`-ом (не `cp`, см. design D5): конфиг `/etc/portage/emerge-ai.json` → `/etc/portage/aimerge.json`, `/var/lib/emerge-ai` → `/var/lib/aimerge`, `/var/log/emerge-ai` → `/var/log/aimerge`, `/var/cache/emerge-ai` → `/var/cache/aimerge` — проверить: `sudo stat -c '%a %U' /etc/portage/aimerge.json` = `600 root`, `sudo grep -o '"model"[^,]*' /etc/portage/aimerge.json` непустой, файлы аудита на месте. `/var/cache/emerge-ai` на хосте не существовал — переносить нечего, каталог создаётся при первом прогоне `changelog`
- [x] 5.3 Перенести тестовую инфраструктуру оверлеев: `/var/db/repos/emerge-ai-test` → `/var/db/repos/aimerge-test` и записи `location`/секций в `/etc/portage/repos.conf/emerge-ai-test.conf`, `emerge-ai-test-base.conf` (имена файлов и секций → `aimerge-test{,-base}`); **плюс найденное на месте**: имя репозитория берётся из `profiles/repo_name` внутри оверлея (design D10), поэтому он тоже перезаписан, и `package.accept_keywords/emerge-ai-test` → `aimerge-test` с содержимым `app-portage/aimerge::aimerge-test **`, а в `package.accept_keywords/app-portage` — `app-portage/aimerge **` (без этого merge в 5.4 не прошёл бы) — проверить: `sudo portageq repos_config /` показывает только `aimerge-test`/`aimerge-test-base` и ни одной записи `emerge-ai`
- [x] 5.3a **Запушить переименование в origin** (`git push origin master`) — без этого merge `9999` физически не может собраться: `git-r3` берёт удалённую ветку, а не рабочее дерево (design D11). Проверено на провале: сборка из непушеного дерева дала `emerge_ai-3.0.82-py3-none-any.whl` и `FileNotFoundError: ${S}/packaging/aimerge.json.default` в `doins`. Проверка: `gh api repos/Sheridan/aimerge/contents/packaging` показывает `aimerge.json.default`, `git ls-remote origin HEAD` = SHA переименования
- [ ] 5.4 Обновить личный оверлей: `babylon_5/app-portage/emerge-ai/` → `babylon_5/app-portage/aimerge/`, ebuild и `metadata.xml` из 3.3, пересоздать `Manifest`; затем `sudo emerge --ask app-portage/aimerge` — проверить: `/var/db/pkg/app-portage/aimerge-9999` и `/usr/bin/aimerge` существуют, `which -a emerge-ai` по-прежнему пусто
- [x] 5.5 Восстановить dev-окружение: `pip install -e .` в репозитории — проверить: `pip show aimerge` печатает `Name: aimerge` (и `Version: 3.0.82`), `python -c "from aimerge import cli"` проходит, `pytest -q -m "not integration"` зелёное → **613 passed, 1 failed** (падающий seam-тест не связан с именем пакета, см. 2.5; утверждение «614 passed», внесённое сюда ранее, было ошибкой — прогон на тот момент не был завершён). Экза `.venv/bin/aimerge` существует, `.venv/bin/aimerge --version` даёт `aimerge 3.0.82` + `Portage 3.0.83` (проверка-major.minor в `compat.py` сходится, bump не нужен — D4)

## 6. Внешние ссылки и интеграционная проверка

- [x] 6.1 Переименовать репозиторий и локальный remote: `gh repo rename aimerge --repo Sheridan/emerge-ai --yes` (выполнил пользователь), затем `git remote set-url origin git@github.com:Sheridan/aimerge.git` и `git push origin master` (см. 5.3a и D11 — без push merge `9999` не собирается) — проверить: `gh repo view --json name -q .name` = `aimerge` и `git ls-remote origin HEAD` проходит на новом URL → подтверждено: `Sheridan/aimerge`, `origin/master` = `75330b1`, старый URL отдаёт редирект на тот же репозиторий
- [ ] 6.2 Смоук read-only поверхностей: `aimerge --version`, `aimerge --help`, `aimerge -p sys-apps/baselayout` — проверить: rc `0`, префикс строк `aimerge: ` (не `emerge-ai: `), в выводе `--help` список собственных флагов начинается с `aimerge own flags`, живой `emerge` не запущен с мутацией. Уже подтверждено на `.venv/bin/aimerge` до merge: `--version` → `aimerge 3.0.82` (rc 0), `--help` → заголовок `aimerge own flags`. Не подтверждается из venv: чтение `/etc/portage/aimerge.json` (файл `0600 root`, читать может только root-экземпляр после 5.4) и `--help`/`--changelog` через guard — они не в allow-списке D6 (решение пользователя: правила остаются строгими)
- [ ] 6.3 Смоук состояния: `aimerge -p`-прогон и `aimerge --changelog` — проверить: новый run-каталог появился в `/var/lib/aimerge/runs`, запись в `/var/log/aimerge/journal.jsonl` использует имя `aimerge`, `--changelog` не падает на пустом `gh_repos`
- [ ] 6.4 Итоговая проверка чистоты переименования: `git show --stat HEAD` для коммита переименования — только переименование, без попутных изменений логики; `git grep -c 'emerge[-_]ai' -- ':!openspec/changes/archive' ':!openspec/changes/rename-project-to-aimerge'` пусто; `pytest -q -m "not integration"` не хуже, чем до переименования: ожидаемый итог — 613 passed и один красный `test_honest_seam_queue_matches_live_resolve` (2.5; воспроизводится на дереве до переименования, чинится отдельным change)
- [ ] 6.5 Переименовать рабочий каталог `~/development/emerge-ai` → `~/development/aimerge` и обновить ссылки в сессии/редакторе — проверить: `git -C ~/development/aimerge status` работает, `openspec list --json` читает корень по новому пути

## Workflow follow-up

- Отдельный change: `queued_cpvs` (`portage_compat.py:57-71`) принимает блокеры
  графа за CPV. Механизм: portage кладёт неразрешённый блок в `altlist()` отдельной
  записью-кортежем `('blocks', root, атом, depth)`; `getattr(entry, "pkg", None) or
  entry` для кортежа даёт сам кортеж, `getattr(pkg, "cpv", pkg)` — тоже, а
  `str(кортеж)` содержит `/` (элемент `root`), поэтому фильтр `"/" in cpv`
  пропускает его в очередь. Следствие: очередь `--pretend` показывает
  `('blocks', '/', '!<dev-util/gdbus-codegen-2.88.4', '8')` вместо CPV, и это
  уходит в дайджест для LLM. Фикс — отбрасывать записи, где первый элемент
  `== "blocks"` (или где `cpv` не строка); фикстура — граф с такой записью, а не
  live-хост. Воспроизводится на текущем хосте: `test_honest_seam_queue_matches_live_resolve`
  красный стабильно, до и после переименования.
  Важное уточнение по частоте: триггер — самый обычный **мягкий блок** мирового
  обновления, `emerge -p -uDN @world` на этом хосте печатает
  `[blocks b ] <dev-util/gdbus-codegen-2.88.4 ("..." is soft blocking
  dev-libs/glib-2.88.4)` и тут же `[ebuild U ] dev-util/gdbus-codegen-2.88.4
  [2.88.2]`. То есть блок не поломка хоста (он снимается тем же прогоном, пакет
  обновляется в этом же наборе), но значит путь с блокером в `altlist()` —
  штатный, а не редкий: любой `--pretend`-прогон с мягким блоком подмешивает
  кортеж в очередь и, соответственно, в дайджест для LLM. Приоритет follow-up
  от этого выше, чем казалось по первому впечатлению.
- Отдельный change: `deny`-правила `opencode.json` привязаны к первому токену,
  поэтому `/usr/bin/emerge …` и `.venv/bin/aimerge …` проходят мимо охраны
  (проверено read-only прогоном `/usr/bin/systemctl is-active`). Закрытие — точечные
  deny на абсолютные пути; широкий `*emerge*` неприемлем, он запретил бы агенту
  читать этот репозиторий.
- Принятые остатки на хосте (не правятся): `/etc/portage/package.accept_keywords/dev-libs:8`
  со старым маркером `# emerge-ai: 2026-11-27 …` (запись аудита, D9);
  `/var/db/repos/aimerge-test/registry.json` с висячим `source` на старый путь и
  `ea-test/foo-1.0.ebuild` с `DESCRIPTION="emerge-ai live stand dummy"` — мусор
  прошлых ручных live-проверок в одноразовых фикстурах, перезаписывается следующим
  прогоном либо сносится вместе с тест-оверлеями.

- Заархивировать change после ревью (`openspec archive rename-project-to-aimerge`); в `archive/` он осядет уже с новым именем, поэтому в архиве сосуществуют оба написания — это принято в design «Open Questions».
- После архивации проверить, что `openspec/specs/**` не содержат `emerge-ai`, а `emerge` как доменный термин остался.
