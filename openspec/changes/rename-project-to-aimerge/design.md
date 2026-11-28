# Design

## Context

См. `proposal.md` — Why. Здесь только то, что формирует способ реализации.

Имя проекта входит в систему четырьмя разными способами, и у каждого свой механизм
замены и своя цена ошибки:

```
 1. идентификаторы кода   src/emerge_ai/  import emerge_ai  attr = emerge_ai.__version__
 2. поверхности хоста     /usr/bin/emerge-ai  /etc/portage/emerge-ai.json
                          /var/lib|log|cache/emerge-ai  /usr/share/emerge-ai
                          EMERGE_AI_* (9 env-имён)
 3. тексты и документы    README, LIVE_CHECKS, DECISIONS, openspec/**, prompts/rules/**
 4. внешние ссылки        github.com/Sheridan/emerge-ai  ~/development/emerge-ai
```

Ключевое ограничение: `emerge` — не только имя. В репозитории ~1400 вхождений
относятся к Gentoo/portage и должны остаться ровно там, где стоят:

| Токен | Почему нельзя трогать |
|---|---|
| `portage_compat.load_emerge_config()`, переменная `emerge_config` | это API portage: `portage.actions.load_emerge_config` (`portage_compat.py:36-39, 74-82`), переименование = `AttributeError` в рантайме |
| `emerge_stub`, `emerge_binary`, `emerge_capturing`, `emerge_args`, `EMERGE_STUB_*` | тестовая обвязка вокруг живого `emerge` (198 + 154 + 72 + 55 вхождений) |
| `emerge-deselect` | имя action в consent-канале (`agent.py:381`, `cli.py:318`, `consent.py:178`), доменное, не имя проекта |
| `Emerge`, «emerge» в прозе и в `DESCRIPTION` ebuild | речь о пакете Gentoo |
| `"emerge *"` и исключения `-p/--pretend/--info/--version` в `opencode.json` | охрана запуска живого emerge, к имени проекта отношения не имеет |

Ещё одно ограничение: состояние живого хоста разработки — единственный случай,
где переименование может уничтожить данные (`/etc/portage/emerge-ai.json` 0600 с
API-ключом, `/var/lib/emerge-ai/{runs,tiers.json,audit.journal.jsonl}`,
`/var/log/emerge-ai/{journal.jsonl,decisions.log}`).

## Goals / Non-Goals

**Goals:**

- После работы `git grep 'emerge[-_]ai'` даёт ноль вне `openspec/changes/archive/` и
  вне каталога самого change (его артефакты обязаны цитировать старое имя; после
  архивации они уедут в `archive/`, и критерий снова станет чистым) — это и есть
  критерий полноты, он же защита от «половинчатого» переименования.
- Ни одно доменное вхождение `emerge` не изменилось: контроль на.diff по списку
  «не трогать» выше.
- Один коммит переименования содержит только переименование: ни одного
  сопутствующего рефакторинга, иначе ревью дифа становится невозможным.
- Хост разработки после всех шагов даёт ровно один установленный пакет и один
  рабочий конфиг с тем же API-ключом.

**Non-Goals:**

- Сохранение обратной совместимости: никаких fallback-чтений `/etc/portage/emerge-ai.json`,
  никаких алиасов `EMERGE_AI_*`, никаких симлинков `/usr/bin/emerge-ai`.
- Переименование чего-либо в `openspec/changes/archive/**` (115 файлов) и в истории git.
- Извлечение хардкода префикса в константу: `ui.PREFIX` (`ui.py:54`) существует, но
  ~30 мест (`config.py:98-164`, `compat.py:33-41`, `flags.py:60`) печатают
  `"emerge-ai: "` буквально и столько же ассертов в тестах сравнивают с этой
  строкой. Сведение их к `PREFIX` — отдельная работа, в этом change только
  механическая замена буквы.

## Decisions

**D1. Порядок замены токенов: `EMERGE_AI_` → `AIMERGE_`, затем `emerge_ai` → `aimerge`,
затем `emerge-ai` → `aimerge`.** Обратный порядок порождает мусор (`emerge-ai` внутри
`EMERGE_AI_...` не встречается, но `AIMERGE_AI_`-подобные осколки появляются при
замене регистра после нижнего). Регистронезависимая замена запрещена — она сотрёт
`Emerge` в прозе и `EMERGE_STUB_*`. Заменяются ровно эти три токена, а не `emerge`.

**D2. Область замены — `git ls-files` минус `openspec/changes/archive/`, а не
рекурсивный проход по дереву.** В дереве лежат `__pycache__/*.pyc`, `.mypy_cache`,
`.pytest_cache`, `.ruff_cache` и `.venv` с editable-установкой
`__editable__.emerge_ai-3.0.82.pth`: кэши удаляются (в них старые строки, править
бессмысленно), `.venv` пересоздаётся (`pip install -e .`) — его содержимое порождено,
а не авторство.

**D3. Каталоги перемещаются через `git mv` до содержательной замены** —
`src/emerge_ai` → `src/aimerge` и
`packaging/app-portage/emerge-ai` → `packaging/app-portage/aimerge`
(+ `emerge-ai-9999.ebuild` → `aimerge-9999.ebuild`, `emerge-ai.json.default` →
`aimerge.json.default`). Иначе замена по путям ломает отслеживание переименований,
и дифф из «33 файла изменено» превращается в «33 удалено + 33 добавлено».
Альтернатива — `git mv` после замены — даёт тот же шум в diff.
Категория остаётся `app-portage`: инструмент про portage, `app-misc` размыл бы
границу, и так уже живёт в личном оверлее под `app-portage`.

**D4. Версия не бампается.** `__version__ = "3.0.82"` (`__init__.py:3`) жёстко
привязана к `sys-apps/portage` по major.minor (`compat.py:37-41`), а не к имени
пакета; bump соврал бы о совместимости. Смена имени пакета — достаточно, чтобы
portage пересобрал его заново: это другой CPV (`app-portage/aimerge-9999`), старые
файлы удаляет `--unmerge` старого.

**D5. Хост: сначала unmerge старого пакета, потом перенос состояния, потом merge
нового.** Порядок важен: merge нового до unmerge оставил бы два конфига, а
`pkg_postinst` нового уже создал бы `/etc/portage/aimerge.json` из packaged
default с пустым `endpoint` — и первый запуск упал бы на «no LLM endpoint
configured», выглядело бы как потеря ключа. Перенос делается `mv` (не `cp`), чтобы
права `0600` и владелец root не пересоздавались; `cp` требует
`install -m 0600 -o root -g root` и оставляет старый файл-дубль с ключом.

**D6. `opencode.json` требует не только замены имён, но и нового правила.**
Сейчас мутации живого emerge запрещены правилами `"emerge *": "deny"` с
исключениями `-p/--pretend/--info/--version`. После переименования агент будет
звать `aimerge`, и эти правила её не покрывают — охрана пропадёт молча. Поэтому
в `opencode.json` добавляются зеркала правил на `aimerge`/`sudo aimerge` (deny по
умолчанию, allow только `--version`, `-p`, `--pretend`, `--info`), а старые
правила на `emerge` сохраняются: прямой `emerge` по-прежнему запрещён.
Разрешения на `rm * /var/db/repos/emerge-ai-test*` переходят на `aimerge-test*`.
Цена строгости принята сознательно: `aimerge --help` и `aimerge --changelog` (по
смыслу read-only) попадают под `deny` в голой форме (через путь —
`.venv/bin/aimerge`, `python -m aimerge` — проходят, см. Risks), потому что
allow-список повторяет ровно исключения живого `emerge` и не расширяется под новые
нужды (решение пользователя при ревью группы 3).

**D7. Спецификации правятся напрямую, без дельта-файлов** (`skip_specs: true`,
обоснование в `proposal.md`). Тот же проход по тому же правилу, что и для кода, —
различается только контролем: для спеков проверяется отсутствие несуществующей
команды в тексте требований.

**D8. GitHub: `gh repo rename aimerge --repo Sheridan/emerge-ai` с последующим
`git remote set-url origin git@github.com:Sheridan/aimerge.git`.** GitHub держит
редирект для clone/pull, но редирект не действует на уже установленный ebuild:
`EGIT_REPO_URI` записан в `/var/db/pkg/app-portage/emerge-ai-9999` и в копии оверлея
`babylon_5/app-portage/emerge-ai/`, поэтому оверлей правится руками, а не «само
обновится». Альтернатива — создать новый репозиторий и архивировать старый: теряет
звёзды/issues и не даёт редиректа, при нулевой выгоде.

**D9. Маркер правок в `/etc/portage/*` не сохраняется.** `config_edit.UNDO_PREFIX`
(`config_edit.py:126`) ищет `# aimerge:` и не читает старый `# emerge-ai:`.
На хосте найдена одна строка аудита от 2026-11-27
(`/etc/portage/package.accept_keywords/dev-libs:8`) — она остаётся как есть:
переписывать её значит подделывать историю, а искать её ради отката не нужно.
Обратная совместимость здесь сознательно не делается (см. Non-Goals).

**D10. Имя репозитория в Gentoo задаёт `profiles/repo_name`, а не секция
`repos.conf`.** На хосте после переноса `/etc/portage/repos.conf/*.conf` и
каталогов `portageq repos_config` продолжал печатать `[emerge-ai-test]` при уже
новом `location`. Источник имени — `profiles/repo_name` внутри оверлея; он и
переписывается в задаче 5.3. Проверка 5.3 формулируется через `portageq`, иначе
она проверяет не то.

## Risks / Trade-offs

- [Наивная замена задевает доменные токены → `AttributeError` на
  `load_emerge_config`, сломанные фикстуры `emerge_stub`] → заменяются ровно три
  токена из D1; после замены — отдельная проверка diff на отсутствие изменений в
  строках с `load_emerge_config`, `emerge_config`, `emerge-deselect`, `EMERGE_STUB_`,
  `emerge_stub`, `emerge_binary`.
- [Потеря рабочего API-ключа при переносе конфига] → `mv` вместо `cp`; перед
  операциями на хосте — `sudo cp -a /etc/portage/emerge-ai.json /root/aimerge-config.bak`;
  после — проверка `test -s` и режима `0600`.
- [Двойной запуск: `/usr/bin/emerge-ai` и `/usr/bin/aimerge` одновременно] →
  порядок из D5; проверка `which -a emerge-ai aimerge` после unmerge и после merge.
- [`__pycache__`/`.pytest_cache` со старыми строками маскируют незаменённые места] →
  удаление кэшей до первого `pytest` (фаза 0), иначе зелёный прогон ничего не
  доказывает.
- [Охрана `opencode.json` молча перестаёт действовать на новую команду] → D6,
  и проверка: агентский прогон `aimerge sys-apps/foo` (мутация) должен быть отклонён
  на уровне разрешения, а не дойти до portage.
- [Зеркало из D6 прикрывает только «голое» имя команды] → проверено на месте:
  правила разрешений привязаны к первому токену команды, поэтому
  `/usr/bin/systemctl …` и `.venv/bin/aimerge --help` проходят мимо deny.
  То есть `deny "emerge *"` никогда не накрывал `/usr/bin/emerge …` — дыра
  предсуществующая, переименование её не увеличивает (зеркало на `aimerge` даёт
  ровно тот же уровень), но и не закрывает. Закрытие — отдельная работа:
  точечные deny на абсолютные пути (`/usr/bin/emerge *`, `/usr/bin/aimerge *`),
  потому что широкий `*emerge*` запретил бы агенту читать этот репозиторий.
- [Состояние хоста, названное старым именем, но не содержащее его внутри] →
  grep-ноль по содержимому такое не ловит: имя репозитория живёт в
  `profiles/repo_name` (D10), файлы резерва инструментов — в собственных именах
  (`config_edit.RESERVE_FILE`). Проверка 5.2/5.3 дополнена поиском по ИМЕНАМ:
  `sudo find /etc/portage /var/lib/aimerge /var/log/aimerge -name '*emerge*'`.
  Найденный `/etc/portage/package.env/lto.pre-emerge-ai` к проекту отношения не
  имеет (ручной список LTO-атомов), поэтому не тронут; `/.snapshots/emerge-ai`
  на хосте не существует — `SNAP_BASE` никогда не использовался, переносить нечего.
- [Полнота «по ощущениям» вместо факта] → единственный критерий — grep-ноль вне
  `archive/`; он же ловит забытые `prompts/rules/*.md` и `LIVE_CHECKS.md`, где имя
  встречается 125 раз в записях ручных прогонов.
- [Откат после merge нового пакета] → все операции на хосте обратимы (`mv` обратно,
  `emerge --unmerge app-portage/aimerge`, `gh repo rename` в другую сторону), но
  записи в аудит-журнале, созданные новым именем, назад не переименовываются —
  это принимается как цена отсутствия пользователей.
- [`LIVE_CHECKS.md` — протокол уже выполненных ручных проверок, в нём имя команды
  часть записанной истории] → переименовывается как документ, который агент и
  пользователь перечитывают для следующих прогонов; расхождение со старыми выводами
  сознательное, история git его не скрывает (коммит переименования виден).

## Migration Plan

```
 0 чистка        rm -rf **/__pycache__ .pytest_cache .mypy_cache .ruff_cache
 (репо)          pip uninstall emerge_ai  (снимает битый editable .pth)

 1 код           git mv src/emerge_ai src/aimerge
 (репо)          git mv packaging/app-portage/emerge-ai packaging/app-portage/aimerge
                 git mv .../emerge-ai-9999.ebuild .../aimerge-9999.ebuild
                 git mv packaging/emerge-ai.json.default packaging/aimerge.json.default
                 замена трёх токенов по git ls-files минус archive/
                 pytest -q  -> зелено

 2 документы     тот же проход по openspec/specs/**, openspec/changes/** (кроме
 (репо)          archive/), README.md, LIVE_CHECKS.md, DECISIONS.md, prompts/rules/**
                 grep-ноль вне archive/  ->  openspec validate

 3 хост          sudo cp -a конфиг в /root/aimerge-config.bak
 (живой)         sudo emerge --unmerge app-portage/emerge-ai
                 sudo mv /etc/portage/emerge-ai.json /etc/portage/aimerge.json
                 sudo mv /var/lib/emerge-ai /var/lib/aimerge
                 sudo mv /var/log/emerge-ai /var/log/aimerge
                 sudo mv /var/cache/emerge-ai /var/cache/aimerge
                 оверлей: babylon_5/app-portage/emerge-ai -> aimerge, ebuild + Manifest
                 repos.conf: emerge-ai-test{,-base}.conf -> aimerge-test{,-base}.conf
                 /var/db/repos/emerge-ai-test -> /var/db/repos/aimerge-test
                 sudo emerge --ask app-portage/aimerge
                 pip install -e .   (в репо, для тестов)

 4 внешнее       gh repo rename aimerge --repo Sheridan/emerge-ai
                 git remote set-url origin git@github.com:Sheridan/aimerge.git
                 gh repo view --json name  -> aimerge
                 smoke: aimerge --version / --help / -p sys-apps/baselayout
                 рабочий каталог ~/development/emerge-ai -> ~/development/aimerge
                 (последним: это ломает текущую сессию/absolute-пути)
```

Откат: `git revert` коммита переименования + `gh repo rename emerge-ai` + обратные
`mv` на хосте + `emerge --unmerge app-portage/aimerge && emerge --ask
app-portage/emerge-ai`. Пока состояние перенесено через `mv` и старый пакет удалён,
откат не теряет данных; точка невозврата — первая мутационная запись, сделанная
новым именем в `/var/log/aimerge/`.

## Open Questions

- Шесть завершённых, но незаархивированных change (`fix-deselect-world-atom` и
  другие) содержат имя в 14 файлах и будут переименованы как live-документы; при
  будущей архивации они уедут в `archive/` уже с новым именем, то есть в архиве
  окажутся оба написания. Влияет только на единообразие архива, ни на спеки, ни на
  разбивку задач — решается при архивации.
- Переименование рабочего каталога `~/development/emerge-ai` технически возможно в
  любой момент и сознательно оставлено последним шагом; если удобнее оставить
  каталог как есть — это не противоречит ничему в change.
