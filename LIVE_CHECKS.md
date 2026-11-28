# Ручные live-проверки (выполняет пользователь)

Агент не создаёт/удаляет снапшоты btrfs и не трогает загрузчик — эти команды
намеренно закрыты в `opencode.json`. Ниже — что прогнать на живом хосте.

## 6.1 btrfs-снапшот на запуске (хост: `/` = btrfs)

```bash
# 1. каталог снапшотов (один раз)
sudo mkdir -p /.snapshots/emerge-ai

# 2. имитация защиты (эмуляция того, что делает emerge-ai при tier<=4 в очереди):
sudo btrfs subvolume snapshot -r / /.snapshots/emerge-ai/manual-test
sudo btrfs subvolume list /.snapshots/emerge-ai   # должен показать manual-test
sudo btrfs subvolume delete /.snapshots/emerge-ai/manual-test

# 3. сквозной прогон (малый план с tier<=4, отказ в подтверждении мерджа):
sudo emerge-ai -a sys-apps/baselayout
#   → до строки Proceed: stdout должен показать tier-digest;
#   → после "Proceed? n" — ничего не мёржится, снапшот остаётся;
#   → проверить: sudo btrfs subvolume list /.snapshots/emerge-ai
#     и удалить осиротевший: sudo btrfs subvolume delete /.snapshots/emerge-ai/<run-id>
```

## 14.2 Полный live-сценарий (после группы 14)

- `emerge-ai -av` (кластерный `-a`): в фазе плана emerge НЕ должен печатать свой
  «Would you like to merge these packages?» — вопрос задаёт только emerge-ai; ответ `n` → abort, rc=0.
  (регрессия: до фикса `-av` не распознавался как `--ask` и уходил в passthrough)
- `emerge-ai <атом> -pv` с гарантированным конфликтом (slot-conflict/masked): rc≠0 и stderr содержит
  «emerge-ai: incident -> consulting agent» + предложение агента. (регрессия: до фикса план-фол
  сохранялся молча, `_maybe_agent` исключал класс plan-failed)
- (факультативно, lenient-emerge-decoding) `LC_ALL=C` и пакет/файл с не-UTF-8 именем в выводе
  emerge: emerge-ai НЕ падает с UnicodeDecodeError — недекодируемые байты печатаются как
  `�` (символ замены) и прогон доходит до штатного rc.
- (split-emerge-stderr) `emerge-ai -av 2>/dev/null` — в stdout нет строк, которые portage писал
  в stderr (например, предупреждений масок); `emerge-ai -av 1>/dev/null` — те же сообщения
  видны в stderr без изменений (до фикса весь stderr emerge лился в stdout).

## Интерактивные вопросы оператора (interactive-incident-dialogue, выполняет пользователь)

Нужен настроенный `endpoint` и настоящий терминал (stdin — TTY, без редиректа).

```bash
# 1. основной сценарий: реальная поломка world на живом хосте, ответить на один вопрос
sudo emerge-ai -uDN @world
#   → при сбое агент, если фактов не хватает, печатает в stderr вопрос
#     (question-цвет) и пронумерованные варианты с последствиями (блок решений:
#     баннер «── decisions», жёлтое тело, зелёные цифры — см.
#     highlight-decisions-and-findings);
#   → строка выбора «[1..n] choose, [c] own text, [q] quit: » — bold yellow;
#   → набранный ответ эхом печатается «> ...» и попадает в proposal модели;
#   → во время ожидания ввода ничего не выполняется: emerge не запускается,
#     мерж и запись состояния не происходят.

# 2. гарантированные выходы — зависнуть невозможно:
#   → «q»/Enter/Ctrl+D → «(no answer)», опрос закрыт до конца запуска,
#     новых вопросов нет, proposal завершается секцией «ASSUMPTIONS:».

# 3. тихие режимы — вопросов нет вовсе, stdin не читается (даже на TTY):
emerge-ai -p <сбойный-атом>
emerge-ai --noninteractive <атом>
emerge-ai <атом> < /dev/null
#   → в stderr нет строки выбора; proposal заканчивается секцией «ASSUMPTIONS:»
```

## Стенд оверлея (группа 11, тесты test_overlay_live.py)

Требуются на машине (пересоздаются инструментом/тестами при необходимости,
в этой сессии репозитории удалены):
- `/etc/portage/repos.conf/emerge-ai-test.conf` (prio 99) и `emerge-ai-test-base.conf` (prio 50)
- `/var/db/repos/emerge-ai-test{,-base}` (sheridan:portage) c `profiles/repo_name`,
  `metadata/layout.conf` (masters=gentoo), `profiles/categories` (`ea-test`)
- dummy `ea-test/foo-1.0` в обоих, Manifest генерирует `overlay.write_manifest`
- реестр `/var/db/repos/emerge-ai-test/registry.json` (journal_id `live-11.2`)

Проверка: `ACCEPT_KEYWORDS="~amd64" emerge -p -v "=ea-test/foo-1.0"` →
`[ebuild N ] ea-test/foo-1.0::emerge-ai-test`.

## Установка из ebuild (add-gentoo-ebuild, выполняет пользователь)

Оверлей настроен по README («Установка (Gentoo, личный оверлей)»).

```bash
# фактическая установка (live-ebuild, ~1-2 мин на git clone)
sudo emerge -1av app-portage/emerge-ai
#   → в конце вывода pkg_postinst: сообщение про созданный/нетронутый
#     /etc/portage/emerge-ai.json и опциональные инструменты

# конфиг по умолчанию создан при первой установке
ls -l /etc/portage/emerge-ai.json
#   → -rw------- root root (reinstall существующий конфиг не затирает)

# CLI работает из корня ФС (вне checkout)
cd / && emerge-ai --version
#   → версия emerge-ai рядом с версией Portage

# prompt-правила резолвятся из /usr/share/emerge-ai/prompts
# (ABI пакета = PYTHON_SINGLE_TARGET, не обязательно eselect-python по умолчанию)
cd / && python3.13 -c "from emerge_ai.prompts import load_rules; print(len(load_rules()))"
#   → число > 0 (2402 на текущих правилах)
```

## План-фаза: LLM-сводка (llm-plan-enrichment, выполняет пользователь)

```bash
# 1) с активным endpoint в /etc/portage/emerge-ai.json
emerge-ai -p app-editors/vim
#   → после строк «emerge-ai plan digest:» идёт блок «llm summary:» (2–5 строк,
#     plain text, раскрашен как LLM-вывод); числа дайджеста не изменились
# 2) без endpoint (временно endpoint="")
emerge-ai -p app-editors/vim
#   → только детерминированный дайджест, «llm summary:» нет, выход 0
# 3) endpoint указывает на нездоровый сервер (например, порт закрыт)
emerge-ai -p app-editors/vim
#   → как в (2): сводка молча отсутствует, план-фаза не сломана, выход 0
```

## Авто-changelog-дайджест (auto-changelog-digest, выполняет пользователь)

```bash
# 1) выключенная опция (default): ключа changelog_digest нет в конфиге
emerge-ai --noninteractive -a =app-misc/small-1.0   # или другой быстрой сборке
#   → после прогона «run digest:» нет, «changelog digest» нет, сетевых обращений нет
# 2) включённая опция с рабочим endpoint
#    в /etc/portage/emerge-ai.json: "changelog_digest": true
emerge-ai --noninteractive -a =app-misc/small-1.0
#   → в stderr «emerge-ai changelog digest:» (LLM-блок), в отчёте
#     /var/lib/emerge-ai/runs/<id>.json поле "changelog" непустое
# 3) endpoint неработоспособен/пустой при включённой опции
#   → raw-перечень «changelog digest (raw):» или warning «changelog digest skipped»,
#     код возврата прогона не меняется

## Префлайт обычного запуска (plan-before-plain-merge, выполняет пользователь)

```bash
# 1) rest-tier без флагов: план-фаза видна, stdout чист
emerge-ai app-misc/small        # обычный запуск, подтвердить [Yes/No] у emerge
#   → в stderr: «emerge-ai plan digest:», info о точке («rest-tier ...» или пусто),
#     в stdout — только дословный вывод emerge (в т.ч. штатный вопрос [Yes/No])
#   → «These are the packages...» ровно один раз: план строится из того же
#     pretend-вывода (avoid-double-resolve-in-plan)
# 2) tier<=4 без флагов: точка создаётся ДО подтверждения
sudo emerge-ai --ask sys-apps/critical   # для сравнения с -a
sudo emerge-ai sys-apps/critical         # без -a: сначала строка снапшота/архива,
#   затем штатный вопрос emerge; при ответе No снапшот удаляется сразу
# 3) мир при недоступном плане (например, битый атом в команде):
emerge-ai --noninteractive =nonexistent/nope
#   → rc != 0, «plan-failed» в отчёте, merge не запускался

## Гейт автономности (wire-autonomy-gate)

```bash
# 1) rest-tier в неинтерактиве — пуск + строка решения в аудите
emerge-ai --noninteractive app-misc/small
sudo tail -1 /var/log/emerge-ai/decisions.log   # decision=apply, tiers=[5]

# 2) tier 1–4 в неинтерактиве — отказ ДО мутаций
sudo emerge-ai --noninteractive sys-apps/critical
#   → rc 7, «autonomy gate: merge blocked», emerge не стартовал,
#     созданная точка вычищена, decision=denied в аудите

# 3) тот же tier 1 с флагом ответственности — пуск с обоснованием
sudo emerge-ai --noninteractive --i-understand-the-risks sys-apps/critical
# 4) интерактив: вердикт ASK печатается, поведение как раньше (вопрос emerge)
```

## Канал отката (wire-rollback-channel)

```bash
# 1) режим восстановления: список + выбор + подтверждение
sudo emerge-ai --rollback
#   → таблица точек (run-id, дата, kind, пакеты), вопрос, разбор последствий,
#     «restored N file(s) ...» для архива; для btrfs-снайма — пошаговая
#     инструкция, снапшот НЕ удалён, система не изменена
# 2) после сбоя tier≤4 в интерактиве: сразу после инцидента — вопрос отката;
#     «n» → артефакты сохранены; в --noninteractive — подсказка --rollback
# 3) sudo emerge-ai --noninteractive --rollback  → отказ + ручная инструкция, rc 5
```

## Петля починки после сбоя (wire-agent-apply-loop)

```bash
# 1) интерактив: реальный сбой merge (например, снятый пакет с удалённого зеркала)
sudo emerge-ai --ask category/pkg
#   → после сбоя: proposal агента + «consent gate» с пронумерованными вариантами;
#     «1» → «applied repair variant [retry], retrying emerge» в stderr и повтор
#     emerge; «q» → «consent gate: quit — system untouched», rc = коду сбоя emerge

# 2) rest-tier в неинтерактиве — применение без вопроса
sudo emerge-ai --noninteractive app-misc/small   # при воспроизводимом сбое merge
#   → «autonomy matrix: --noninteractive: rest-tier ...» + «applied repair variant»,
#     строка decision в /var/log/emerge-ai/decisions.log

# 3) tier 1–4 без флага — отказ, система не тронута
sudo emerge-ai --noninteractive sys-apps/critical
#   → «consent gate: auto-repair refused at tiers ...», предложение в выводе,
#     emerge не повторялся, rc = коду сбоя

# 4) лимит циклов: два неудачных повтора подряд
#   → «agent loop: repair limit (2 apply->retry cycles) reached; showing the
#     final report only», третий цикл агента не запускается, rc последнего сбоя;
#     в /var/lib/emerge-ai/runs/<id>.json поле "repair" с обеими попытками

# 5) без endpoint в конфиге петля не включается вовсе: после сбоя нет ни
#    «consent gate», ни вопросов — только proposal/отчёт как раньше
```

## Журнал решений (wire-journal-writer, выполняет пользователь)

```bash
# 1) успешное применение фикса (повтор emerge отработал rc=0) — ровно одна запись
sudo tail -1 /var/log/emerge-ai/journal.jsonl
#   → JSON со solution/actions, "verified_by": "retry-exit-0", run_id прогона;
#     запись появляется и на rest-tier ветке, и на интерактивной

# 2) неудачный повтор — записи в журнале нет (только верифицированные фиксы)

# 3) дедуп прецедентов: повторить тот же сбой (отпечаток stderr+класса совпадает)
#   → в запросе модели секция «SUCCESSFUL PRECEDENT ... reuse of a
#     successful precedent»; в stderr-эхо промпта она видна при -v

# 4) unwritable журнал (chmod 000 /var/log/emerge-ai/journal.jsonl):
#   → «journal write failed: ... — run unaffected» в stderr, применение и
#     повтор emerge не тронуты, rc не изменён
```

## Исчерпание лимита агентом (handle-agent-limit-exhaustion, выполняет пользователь)

```bash
# 1) интерактив, усечение по токенам (маленький max_tokens или очень длинный лог):
sudo emerge-ai --ask category/pkg
#   → вопрос через штатный канал опроса: «продолжить разбор / свернуть разбор /
#     завершить»; «продолжить» — разбор с точки остановки (фрагмент помечен
#     как незавершённый), увеличенный бюджет раундов; второй раз за разбор
#     вопрос не задаётся никогда

# 2) «свернуть разбор» → итог из накопленного; нераспознанный ответ / EOF / [q]
#    трактуются как «завершить»: фрагмент с пометкой
#    «[answer truncated at the token limit — unfinished fragment, not a
#    final conclusion]» + детерминированные варианты

# 3) неинтерактив:
sudo emerge-ai --noninteractive --i-understand-the-risks category/pkg
#   → вопросов нет; «agent limit exhausted (tokens|rounds): ...» в stderr;
#     sudo tail -1 /var/log/emerge-ai/decisions.log → "kind": "agent-limit",
#     "decision": "finish", reason, incident_class, run_id;
#     rc = коду сбоя emerge (не изменён)

# 4) усечённые по лимиту вызовы инструментов НЕ исполняются: в stderr-эхо нет
#    ни одной команды из обрезанного tool-call

# 5) прочий сбой агента (выключить endpoint) — как раньше: «agent unavailable»
#    или «agent stopped: ...», строки «agent limit exhausted» нет
```

## Строки активности и дампы (-v) (add-progress-logging, выполняет пользователь)

```bash
# 1) анонсы по умолчанию (без -v):
sudo emerge-ai -p app-editors/vim
#   → в stderr видны «emerge-ai: running: emerge ...» (полный argv) и
#     «emerge-ai: sending request to LLM (model=..., N messages, tools=...)»
#     до появления LLM-сводки; тел запросов в выводе НЕТ

# 2) детализация при -v (человекочитаемый дамп запроса):
sudo emerge-ai -pv app-editors/vim 2>/tmp/verbose.log
#   → в /tmp/verbose.log блок дампа: первая строка «emerge-ai: request:
#     model=... temperature=... messages=N tools=M body=X chars», затем по строке
#     на сообщение «emerge-ai:   [n] роль · N chars: превью», tool-call'ы вида
#     «tool_calls: имя(key=value)», список инструментов «tool[i/M] имя — описание»;
#     длинное поле срезано плашкой «…[capped, N chars total]», переполненный блок —
#     плашкой «dump truncated: shown X of Y lines»; рядом «LLM answered in X.Xs
#     (finish=...)»; emerge получил -v без изменений (его вывод не сломан)
#   → сериализованного JSON в дампе нет: ни «request payload:», ни фигурных скобок
grep -c 'request payload:' /tmp/verbose.log    # 0
grep -c '[{}]' /tmp/verbose.log                # 0 строк с JSON-фигурными скобками

# 3) секрет не утекает: при api_key в конфиге ни в одном дампе stderr нет ни
#    значения ключа (сравни с literal из конфига), ни заголовка Authorization;
#    вместо значения — плашка «***», размеры в «N chars» считаются по исходному тексту
grep -F "$(python -c 'import json;print(json.load(open("/etc/emerge-ai.json"))["api_key"])')" \
    /tmp/verbose.log                            # пусто

# 4) stdout не тронут: sudo emerge-ai -p app-editors/vim 1>/tmp/out.txt 2>/dev/null
#    → в /tmp/out.txt только вывод emerge, строк «emerge-ai: running:» нет

# 5) tool-call'и агента (сбойный атом, разбор): до каждого инструмента строка
#    «emerge-ai: tool: <имя>(<аргументы>)», длинные аргументы срезаны плашкой
```

## Живой вывод LLM при -v (stream-llm-output-live, выполняет пользователь)

```bash
# 1) инкрементальный показ под -v:
sudo emerge-ai -pv app-editors/vim
#   → рассуждения («[reasoning] ...», тусклый цвет) появляются по мере генерации,
#     затем основной текст — целыми строками; строка «LLM answered in X.Xs
#     (finish=...)» выходит ПОСЛЕ всего текста ответа и ровно одна за вызов
#     (при usage эндпоинта — с плашкой [tokens N+M])

# 2) без -v стриминга нет: запрос однократный, вывод появляется целиком:
sudo emerge-ai -p app-editors/vim 2>/tmp/quiet.log
#   → в /tmp/quiet.log нет ни предупреждений про stream, ни «[reasoning]»

# 3) --ask под -v — каждый ход модели ровно один раз:
sudo emerge-ai -a app-editors/vim -v
#   → текст каждого хода (рассуждения, ответ, tool-вызовы) напечатан один раз;
#     финальный блок «agent proposal:» содержит пометку
#     «(the proposal was shown live above)» и НЕ дублирует текст

# 4) QUESTION-строка в потоке окрашена целиком (TTY, не pipe):
#   → строка, начинающаяся с «QUESTION:», целиком в question-цвете, несмотря на
#     доставку фрагментами; в pipe (2>/tmp/x) те же тексты без escape-кодов

# 5) эндпоинт без поддержки потока (подставить временный endpoint, отдающий
#    обычный JSON на stream:true):
sudo emerge-ai -pv app-editors/vim 2>/tmp/fallback.log
#   → ОДНО предупреждение «...; single request instead», ответ показан как
#     раньше, прогон продолжен; в дампе запроса повтор без «stream»
#   → при обрыве потока ПОСЛЕ первого показанного фрагмента — ошибка
#     «LLM request failed», без повтора и без задвоенного текста на экране

# 6) коды выхода и вывод emerge не изменились: см. базовые секции выше
#    (passthrough stdout, rc) — поведение идентично прогону до изменения
```

## Язык ответов LLM (fix-llm-response-language, выполняет пользователь)

```bash
# 1) в конфиге {"language": "ru"} (или LANG=ru_RU.UTF-8 при language: auto):
sudo emerge-ai -p app-editors/vim
#   → LLM-сводка дайджеста плана по-русски; ключевые слова tier/findings — нет

sudo emerge-ai --ask category/pkg   # инцидент: proposal агента по-русски

# 2) структурные ответы не разъезжаются: при language: ru разбор etc-update и
#    анализ consent-меню печатают human-поля (reason/comment) по-русски, а
#    JSON-ключи/коды (keep-current/merge, ключи вариантов) работают как прежде

# 3) "language": "en" — весь LLM-вывод на английском;
#    "language": "xx" — директива использует значение как есть
```

## Рассуждения при -v на каждом вызове (fix-verbose-thinking-output, выполняет пользователь)

```bash
# 1) сводка дайджеста:
sudo emerge-ai -pv app-editors/vim 2>/tmp/p.log
#   → в /tmp/p.log строка «[reasoning] ...» до/рядом с llm summary (endpoint
#     отдаёт reasoning_content по умолчанию)
sudo emerge-ai -p app-editors/vim 2>/tmp/q.log
#   → «[reasoning]» в /tmp/q.log НЕТ

# 2) agent-петля (сбойный атом, интерактив): каждое рассуждение модели
#    напечатано ровно один раз за ход — дублей «[reasoning]» подряд быть не должно:
sudo emerge-ai --ask category/pkg 2>/tmp/agent.log
grep -c '\[reasoning\]' /tmp/agent.log   # совпадает с числом ответов модели

# 3) прочие прямые вызовы при -v: consent-анализ (свободный текст в меню),
#    etc-update-сверка, changelog-дайджест — везде «[reasoning]» появляется
#    в stderr; без -v тишина; в pipe цвет не просачивается
```

## Язык вопросов оператору (localize-llm-questions, выполняет пользователь)

```bash
# 1) в конфиге {"language": "ru"} и интерактив с реальным сбоем:
sudo emerge-ai --ask category/pkg
#   → вопрос агента (question), варианты (label) и последствия (consequences)
#     на русском; служебная строка выбора «[1..n] choose, [c] own text, [q] quit: »
#     и все анонсы emerge-ai остаются на английском
#   → набранный русский/английский ответ работает как прежде (ключи схем
#     не переводятся, whitelist-ключи не зависят от языка)

# 2) {"language": "en"} — вопросы на английском; дампы запросов при -v
#    (блок «request: ...») совпадают с таковыми до изменения:
#    в описании ask_operator нет никакой языковой плашки
sudo emerge-ai --ask category/pkg -v 2>/tmp/ask.log
grep -o 'tool_calls: ask_operator' /tmp/ask.log | head -1        # вызов виден по имени
grep -o 'tool\[.*ask_operator — Ask the[^·]*' /tmp/ask.log | head -1  # хвост без плашки

# 3) неинтерактив (--noninteractive, pipe): вопросов нет вообще, список
#    инструментов без ask_operator — язык ни на что не влияет
```

## Правка package.* на каталожной раскладке (fix-package-edit-directory-target, выполняет пользователь)

Хост с `/etc/portage/package.accept_keywords/` как каталогом (штатная раскладка
Gentoo) — на нём раньше был `IsADirectoryError` после согласия оператора.

```bash
# 0) раскладка видна (каталог, а не файл):
ls -la /etc/portage/package.accept_keywords | head

# 1) интерактивный прогон с гарантированно masked-находкой (в файле категории
#    нужной строки нет):
sudo emerge-ai app-container/edk2-bin
#   → в consent-меню пункт «add '=app-container/edk2-bin-<v> ~amd64' to
#     package.accept_keywords/app-container and re-plan» — путь с категорией,
#     а не просто «package.accept_keywords», и та же цель в строке «undo: …»
#   → выбор пункта: в stderr «emerge-ai: editing
#     /etc/portage/package.accept_keywords/app-container: + =app-container/…»,
#     затем «re-resolved after repair: plan is clean now» и мердж

# 2) запись легла в файл категории, раскладка не переписана:
test -d /etc/portage/package.accept_keywords            # каталог цел
grep -n emerge-ai /etc/portage/package.accept_keywords/app-container  # строка с маркером
ls -la /etc/portage/package.accept_keywords             # прочие файлы категорий целы

# 3) отмена по аудит-маркеру видит строку внутри каталога (пустой файл остаётся):
sudo python3 -c "
from emerge_ai import config_edit
print(config_edit.remove_by_run('<run-id>'))            # […/package.accept_keywords/app-container]
print(config_edit.remove_by_run('<run-id>'))            # [] — идемпотентно
"

# 4) недостижимая цель — отказ с путём и причиной, не traceback:
sudo mkdir -p /etc/portage/package.mask/app-misc        # «файл категории» — каталог
sudo emerge-ai app-misc/<masked-pkg>                    # выбрать правку вида mask
#   → «package-edit refused: cannot write /etc/portage/package.mask/app-misc: …»,
#     меню показывается заново (q — выход без изменений системы),
#     никакого IsADirectoryError в выводе
sudo rmdir /etc/portage/package.mask/app-misc
```

## Правка лицензий идёт в package.license (fix-license-channel-filename, выполняет пользователь)

Раньше вид `accept_license` писал в `package.accept_license` — файл, который
portage не читает: запись выглядела починкой, мердж не менялся.

```bash
# 0) нечитаемого файла быть не должно (и до, и после):
test ! -e /etc/portage/package.accept_license && echo ok

# 1) хост с файловой раскладкой: прогон с находкой unaccepted license
sudo emerge-ai <категория>/<пакет>     # пакет с непринимаемой лицензией
#   → consent-пункт правки лицензий называет package.license
#   → в stderr «emerge-ai: editing /etc/portage/package.license: + …»
#   → после выбора: строка с аудит-маркером в package.license, перезапущенный
#     emerge не сообщает о непринимаемой лицензии

# 2) файл создан/дописан, лишнего нет:
grep -n emerge-ai /etc/portage/package.license
test ! -e /etc/portage/package.accept_license && echo ok
ls -la /etc/portage | grep -c '^d.*package\.'   # раскладка не переписана

# 3) каталожная раскладка (если /etc/portage/package.license — каталог):
test -d /etc/portage/package.license && \
  grep -n emerge-ai /etc/portage/package.license/<category>

# 4) отмена по аудит-маркеру чистит только строку прогона:
sudo python3 -c "
from emerge_ai import config_edit
print(config_edit.remove_by_run('<run-id>'))   # […/package.license]
print(config_edit.remove_by_run('<run-id>'))   # [] — идемпотентно
"

## Подсветка блоков решений и типов находок (highlight-decisions-and-findings, выполняет пользователь)

Нужен настоящий терминал (TTY) и возможность повторить команду в pipe.

```bash
# 1) consent-меню в цветном терминале (деградированный план, любой masked-пакет):
sudo emerge-ai -av =app-container/edk2-bin
#   → перед списком: пустая строка и баннер «── decisions ──…» (жёлтый жирный),
#     после блока — пустая строка;
#   → строки вариантов «[1] …» жёлтые, цифра «[1]» — зелёная; pros/cons/risks
#     тоже жёлтые; «[c]»/«[q]» без зелёного (общее тело блока).

# 2) вопрос агента (живой endpoint, интерактивный прогон с дефицитом фактов):
sudo emerge-ai -uDN @world
#   → строка вопроса сохраняет question-цвет из llm_colors; опции — жёлтый
#     блок с зелёными цифрами «1.»; кастомный llm_colors (в т.ч. content=off)
#     цвета блока не меняет.

# 3) advisory-отчёт триажа деградированного плана (rc 0, что-то не смержится):
sudo emerge-ai -uDN @world -av
#   → TTY: теги [severity]/[dep-conflict]/[conflict]/[empty-update] красные,
#     [masked]/[world-file]/[dep-required]/[config-updating] жёлтые,
#     [important]/[warning] циановые; окрашен только тег, остальная строка без кода;
#   → kind-токены строк «llm findings» дайджеста — та же шкала.

# 4) plain-режимы: тот же текст без escape-кодов, разделимость видна:
sudo emerge-ai -uDN @world -av >run.log 2>&1; grep -c $'\x1b' run.log   # → 0
NO_COLOR=1 sudo emerge-ai -av =app-container/edk2-bin                    # в TTY без кодов
#   → в файле видны «── decisions», пустые строки-разделители и теги [{kind}]

## Очередь со статус-флагами (fix-queued-plan-parsing, выполнено агентом 2026-11-27)

Стенд: очередь `-auDN @world` из двух обновлений, оба `[ebuild     U ~]`
(dev-libs/jemalloc-5.4.0-r2, app-misc/yazi-26.9.1). Прогонялось от исходников репо
(`sudo env PYTHONPATH=$PWD/src python3 -m emerge_ai.cli ...`).

```bash
# 1) digest считает обновления с флагами статуса (было: пустая очередь):
sudo emerge-ai -p -auDN @world
#   → проверено: «tier 5: 2 pkg(s) — dev-libs/jemalloc-5.4.0-r2, app-misc/yazi-26.9.1»

# 2) consent-меню описывает реальную очередь merge:
sudo emerge-ai -auDN --ask @world        # в TTY; q — выход без изменений
#   → проверено: «[2] merge the queue as shown (2 package(s), tiers 5;
#     5 finding(s) stay unresolved)» (до фикса: «0 package(s), tiers unknown»);
#     не-TTY stdin — штатный legacy «Proceed?» без диалога, EOF → «interrupted;
#     nothing changed», rc 0, ни снапшота, ни merge не создано

## Советник в consent-диалоге (consent-question-channel, выполнено агентом 2026-11-27)

Стенд: деградированный `-auDN @world` (конфликт sys-firmware/edk2-bin с пином qemu),
эндпоинт strata/qwen3.8-flash. Прогон в TTY (`script`) от исходников репо; свободный
текст вводится в ответ consent-меню.

```bash
sudo emerge-ai -auDN --ask @world      # в TTY; далее — вопрос свободным текстом
#   → проверено, раунд 1 («для чего нужен edk2-bin и что сделать, чтобы он обновился?»):
#     канал прочитал plan-артефакт, world, elog (tool: read_file_window/grep_log),
#     сделал pretend-гипотезу (tool: pretend_emerge), на исчерпании раундов
#     инструментов получил заключительный ответ без инструментов (finish=stop) —
#     содержательный ответ по-русски (зачем пакет, почему 202608_p1 не появляется,
#     что делать), затем перерисованное меню, ни одно действие не исполнено;
#     до фикса тот же вопрос ронял запуск (AttributeError на Response)
#   → проверено, раунд 2 («какой пункт меню ты советоваешь исходя из прошлого ответа?»):
#     запрос ушёл с историей (23 сообщения, включая прошлый tool-обмен и ответ),
#     ответ сослался на прошлый раунд («deselect не выбирайте»); q → «operator
#     aborted; nothing changed», rc 0 (--ask), ни снапшота, ни merge не создано

## Deselect по дословной строке world (fix-deselect-world-atom, выполняет пользователь)

Живой хост. В `/var/lib/portage/world` есть `sys-firmware/edk2-bin` (установлен
202408_p1, кандидат обновления 202608_p1) и слотовые записи `sys-devel/gcc:14`/`:15`.
Проверка меняет мир — делать после копии world.

```bash
cp -a /var/lib/portage/world /var/lib/portage/world.bak.$$
sudo emerge-ai -auDN @world          # в TTY; находка конфликта sys-firmware/edk2-bin
#   → пункт меню deselect формулируется без версии кандидата: «remove
#     sys-firmware/edk2-bin from the world set (emerge --deselect
#     sys-firmware/edk2-bin)» — атом = дословная строка world, не CPV находки;
#   → выбрать пункт: команда снимает ровно одну строку world (прочитать файл:
#     запись ушла, соседние слоты/пакеты не задеты);
#   → повторить deselect уже снятой записи (или слота, которого нет в world): emerge
#     печатает «No matching atoms found in "world"» и выходит с кодом 0 — emerge-ai
#     помечает это «no effect», печатает точную ручную команду, НЕ засчитывает
#     починку в repairs и НЕ предлагает вариант вновь (меню пересобирается без него);
#   → до фикса слот-атом = CPV находки (sys-firmware/edk2-bin-202608_p1) и emerge
#     обрывался: «!!! 'sys-firmware/edk2-bin-202608_p1' is not a valid package atom».
cp -a /var/lib/portage/world.bak.$$ /var/lib/portage/world   # вернуть мир
```
