# Design

## Context

См. proposal.md — Why. Текущее состояние, релевантное для решений:

- `pyproject.toml`: setuptools PEP 517, `requires-python >=3.11`, dynamic version
  (`emerge_ai.__version__ = "3.0.82"`), entry-point `emerge-ai = emerge_ai.cli:main`,
  packages find `where=["src"]`.
- `src/emerge_ai/prompts.py:16-20`: `rules_dir()` = env `EMERGE_AI_PROMPTS_DIR` ??
  относительный `./prompts` от CWD — installed-сценарий не покрыт (spec `config-prompts`
  уже требует `/usr/share/emerge-ai/prompts`).
- Рантайм-вызовы хост-инструментов: `findmnt` (util-linux, деградирует в "unknown"),
  `btrfs` (fallback tar), `genlop` ("нет данных"), `git` (толерантность к недоступности),
  GitHub releases через urllib (без gh).
- Хост разработки: Python 3.14.7, portage importable из системы; pytest с
  `pythonpath=["src"]`, маркер `integration`.
- Репозиторий GitHub публичный (HTTPS 200); origin — SSH.
- Граница сессии (DECISIONS.md): запрещены живой emerge кроме `-p/--info/--version`,
  ebuild merge, снапшот-мутации — верификация ebuild статическая + pretend.

## Goals / Non-Goals

**Goals:**
- Один self-contained ebuild-файл в репо, готовый к копированию в личный оверлей.
- Установка, в которой CLI работает «из коробки» с любого CWD (правила, portage import).
- Воспроизводимая проверка без мутаций живой системы.

**Non-Goals:**
- Инфраструктура оверлея (metadata/layout.conf, profiles/repo_name, CI-валидация) — вне объёма.
- Версионные ebuild-релизы по тегам, генерация Manifest/подписи, публикация в gpo.
- Изменения поведения CLI, конфига, агентского цикла.

## Decisions

1. **Live `emerge-ai-9999.ebuild` + `git-r3`, а не tarball-снапшот.**
   `EGIT_REPO_URI="https://github.com/Sheridan/emerge-ai.git"` (HTTPS вместо SSH — анонимный
   fetch), `EGIT_BRANCH="master"`. Версия приложения живёт в `__version__`, PV=9999 для
   portage — привязка к portage остаётся runtime-проверкой major.minor, эволюция правил
   не требует пере-рэппинга ebuild. Альтернатива (snapshot-архив по тегу) отклонена: требует
   тегов на каждый релиз, против «живого» характера проекта, выбрана пользователем live-модель.
2. **`EAPI=8`, `distutils-r1` + `git-r3`, `DISTUTILS_SINGLE_IMPL=1`.**
   PEP 517-сборка через setuptools делает distutils-r1 единственной адекватной основой.
   Single-impl (PYTHON_SINGLE_TARGET) — чтобы `import portage` резолвился одному ABI: при
   multi-impl каждый установленный скрипт требовал бы portage, собранный под тот же impl.
   `PYTHON_COMPAT=( python3_{11..14} )` по `requires-python >=3.11` и хосту 3.14.
   Альтернатива multi-impl отклонена: дублирование CLI и риск ABI-несовпадения с portage.
3. **Метаданные:** `SLOT="0"`, `LICENSE="GPL-3+"`, live-ebuild без `KEYWORDS`
   (приёмка через `package.accept_keywords = sys-apps?/... ~amd64` или `**`), `IUSE="test"`,
   `RDEPEND="sys-apps/portage sys-apps/util-linux test? ( >=dev-python/pytest-7 )"`.
   btrfs-progs/genlop/git — не в RDEPEND (все опциональные пути деградируют штатно),
   только pkg_postinst-подсказка. util-linux в RDEPEND — findmnt используется всегда
   (rollback/prompts), пакет и так есть в @system.
4. **`src_install`: типовой `python_install` + `doins -r prompts/. →
   /usr/share/emerge-ai/prompts`.** `prompts/` не входит в wheel (вне `src/`), поэтому ставится
   вручную через `insinto /usr/share/emerge-ai`. DOCS="README.md". Альтернатива (package-data
   через setuptools) отклонена: меняет раскладку pip-дистрибутива ради ebuild-специфики.
5. **Fallback правил в коде: `env → ./prompts (dev) → /usr/share/emerge-ai/prompts`.**
   Минимальная правка `rules_dir()`: если env-дир и `./prompts` отсутствуют — вернуть
   install-путь; если отсутствуют все три — существующая ошибка `FileNotFoundError`,
   текст расширить списком проверенных путей (spec-сценарий «Правила отсутствуют»).
   `EMERGE_AI_PROMPTS_DIR` и dev-раскладка сохранены приоритетнее install-пути.
6. **`src_test`: `python_test -- -m "not integration"`.** Интеграционные тесты
   (маркер в pyproject: живой portage/strata) в build-sandbox не запускаются;
   distutils-r1 ставит pytest через `test?`. Конфиг emerge-ai в фазах сборки не читается
   (тесты на стабах) — отдельных src_unpack-хуков не нужно.
7. **Хранение в репо: `packaging/app-portage/emerge-ai/emerge-ai-9999.ebuild`** —
   пути ниже `packaging/` зеркалят категорию/пакет, копия в оверлей = `cp -r`.
   Секция «Установка (Gentoo)» в README: подключение оверлея, accept_keywords, конфиг,
   ручные live-проверки (дополняет LIVE_CHECKS.md).

## Risks / Trade-offs

- [Репозиторий станет приватным/переименован] → ebuild упадёт на fetch; риск отмечен,
  проверка живёт в pkgcheck/ручной проверке актуальности URL; вариант — зеркало, отложен.
- [portage без поддержки PYTHON_SINGLE_TARGET-целевого ABI] → `import portage` падает в
  runtime; mitigation: RDEPEND на sys-apps/portage + сообщение runtime-проверки версии;
  pkg_pretend-проверка ABI сознательно не вводится (хрупко эвристикой).
- [PV=9999 ≠ версия приложения] → пользователи ожидают «3.0.82» в `qlist`/emerge -pv;
  принято: версионность обеспечивает runtime-привязка + `--version`; live-модель выбрана.
- [git-r3 тянет git в DEPEND] → приемлемо, dev-vcs/git стандарт BDEPEND; Manifest для
  live-ebuilds не требует digest (local overlay, `repos.conf` без `sign`).
- [pytest в unit-тестах видит системный portage] → и должно: integration-маркер отделён;
  тесты со стабами не полагаются на хост.

## Migration Plan

Обычная установка пакета; откат = `emerge --unmerge app-portage/emerge-ai` (пакет ничего
не пишет в /etc сам). Для checkout-пользователей поведение не меняется (dev-раскладка
в приоритете).

## Open Questions

- Нужно ли со временем `@rebuild`-безопасное имя слота (`SLOT="3.0"` по major.minor
  portage) — отложить до появления версионных ebuild.
