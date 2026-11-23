# Tasks

## 1. Разрешение директории prompt-правил (код)

- [x] 1.1 Изменить `rules_dir()` в `src/emerge_ai/prompts.py`: приоритет env
      `EMERGE_AI_PROMPTS_DIR` → существующий `./prompts` от CWD → `/usr/share/emerge-ai/prompts`;
      при отсутствии всех трёх — ошибка `FileNotFoundError` со списком проверенных путей;
      покрыть юнит-тестами (env перебивает, dev-checkout из tmp-cwd, installed-fallback через
      monkeypatch install-пути, «всё отсутствует» → текст с путями) и проверить зелёным
      `pytest -m "not integration"`

## 2. Ebuild и упаковка

- [x] 2.1 Создать `packaging/app-portage/emerge-ai/emerge-ai-9999.ebuild` по design.md:
      EAPI=8, `distutils-r1`+`git-r3`, `DISTUTILS_SINGLE_IMPL=1`,
      `PYTHON_COMPAT=( python3_{11..14} )`, `EGIT_REPO_URI` HTTPS
      `https://github.com/Sheridan/emerge-ai.git`, `LICENSE="GPL-3+"`, `SLOT="0"`, без KEYWORDS,
      `IUSE="test"`, `RDEPEND="sys-apps/portage sys-apps/util-linux"`, `BDEPEND` pytest на
      `test?`; `src_install`: `python_install` + `insinto /usr/share/emerge-ai` +
      `doins -r prompts/.`; `src_test`: `python_test -- -m "not integration"`;
      `pkg_postinst`: конфиг `/etc/portage/emerge-ai.json` (0600, обязательный `endpoint`) и
      опциональные `sys-fs/btrfs-progs`/`app-portage/genlop`/`dev-vcs/git`; проверка — из
      задачи 3.1

## 3. Верификация без мутаций живой системы

- [x] 3.1 Разместить ebuild во временном локальном оверлее (`metadata/layout.conf`, `masters =`)
      и прогнать `pkgcheck scan` — ноль ERROR/WARN; при предупреждениях — поправить ebuild
      и повторить
- [x] 3.2 Dry-run разрешения зависимостей на хосте: временная запись repos.conf
      (`/etc/portage/repos.conf/emerge-ai-pkg`), `emerge -1pv app-portage/emerge-ai`
      (только pretend, разрешено границей сессии) — ebuild парсится, видны зависимости
      portage/util-linux/git и single-impl python; временную запись удалить
- [x] 3.3 Полный unit-прогон `pytest -m "not integration"` зелёный (после правки 1.1);
      smoke: `cd /tmp && EMERGE_AI_RULES= python3 -c "import sys; sys.path.insert(0,'src');
      from emerge_ai.prompts import rules_dir; print(rules_dir())"` из пустого каталога без env
      возвращает install-путь

## 4. Документация

- [x] 4.1 Секция «Установка (Gentoo, личный оверлей)» в `README.md`: копирование
      `packaging/app-portage/emerge-ai/` в оверлей, `package.accept_keywords` для live-версии,
      `emerge app-portage/emerge-ai`, создание конфига 0600, опциональные инструменты;
      проверка — содержание секции соответствует флагам и зависимостям ebuild из 2.1
- [x] 4.2 В `LIVE_CHECKS.md` добавить ручные проверки пользователя (выполняет пользователь):
      фактическая `emerge -1av app-portage/emerge-ai`; `emerge-ai --version` из `/`;
      `cd / && python -c "from emerge_ai.prompts import load_rules; print(len(load_rules()))"`
      > 0 (правила резолвятся вне checkout); вывод postinst содержит инструкцию про конфиг

## Workflow follow-up

- После применения: реальный live--install и чек-лист 4.2 выполняет пользователь на своём хосте
  (вне песочницы сессии, как 14.2 в README)
