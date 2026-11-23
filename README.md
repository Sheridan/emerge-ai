# emerge-ai

AI-ассистированная обёртка над Gentoo `emerge`: исполняет сам `emerge`
(passthrough), а сбои чинит LLM-агент в песочнице, с явным согласием
человека на мутации системы и путём отката. Версия проекта жёстко
привязана к `sys-apps/portage` (совместимость по major.minor).

## Установка (Gentoo, личный оверлей)

Ebuild лежит в `packaging/app-portage/emerge-ai/` — live-версия (`9999`,
`distutils-r1` + `git-r3`, один `PYTHON_SINGLE_TARGET` из профиля).

1. Скопировать категорию в личный оверлей:

   ```
   mkdir -p <overlay>/app-portage
   cp -r packaging/app-portage/emerge-ai <overlay>/app-portage/
   ```

2. Сгенерировать Manifest (портage маскирует пакеты локального репозитория
   без него): `ebuild <overlay>/app-portage/emerge-ai/emerge-ai-9999.ebuild manifest`

3. Разрешить live-версию (в ebuild нет KEYWORDS):

   ```
   echo "app-portage/emerge-ai **" | sudo tee /etc/portage/package.accept_keywords/emerge-ai
   ```

4. Установить: `sudo emerge -1av app-portage/emerge-ai`
   (рантайм-зависимости `sys-apps/portage` и `sys-apps/util-linux` подтянутся
   автоматически; `sys-fs/btrfs-progs`/`app-portage/genlop` — опциональны).

После установки:

- конфиг `/etc/portage/emerge-ai.json` (`chmod 0600`, root) создаётся автоматически
  при первой установке, если отсутствует (при обновлениях ваш файл не меняется;
  шаблон — `/usr/share/emerge-ai/emerge-ai.json.default`); задайте в нём `"endpoint"`
  (OpenAI-compatible base URL) и `"model"`; без endpoint каждый LLM-вызов явно
  падает, passthrough-`emerge` при этом работает;
- prompt-правила читаются из `/usr/share/emerge-ai/prompts` (в dev-checkout —
  `./prompts` от CWD; переопределение — env `EMERGE_AI_PROMPTS_DIR`).

## Запуск

```
emerge-ai <любые флаги emerge>
emerge-ai --version     # версия emerge-ai рядом с версией Portage
```

## Собственные флаги

Все прочие аргументы передаются `emerge` дословно.

| Флаг | Действие |
| --- | --- |
| `--noninteractive` | без вопросов в TTY; автономные действия — только rest-tier, остальное fail-closed (лог + ненулевой выход) |
| `--i-understand-what-i-am-doing-and-take-full-responsibility-for-consequences` | полная автономия, включая исполнение отката |

`-v`/`--verbose` (флаг emerge, передаётся ему без изменений) дополнительно
включает вывод рассуждений модели (`[reasoning] ...` в stderr); по умолчанию
выключен. В старых конфигах ключ `reasoning_show` игнорируется с
предупреждением.

## Перехват `-a/--ask` и `-p/--pretend`

- `-p`/`--pretend`: план исполняет `emerge`, вывод печатается дословно,
  затем emerge-ai добавляет LLM-обогащение плана.
- `-a`/`--ask`: сначала показывается план (как `-p`), затем обогащение,
  затем **финальный вопрос `Proceed?` задаёт emerge-ai**. Без подтверждения
  merge не запускается никогда; EOF на stdin = отказ. Слияние после
  подтверждения запускается без `-a`/`-p`.
- `--noninteractive -a`: вопроса нет; merge продолжается (гейт risk-tiers
  сработает на фазе мутаций), решение логируется.

## Конфигурация

`/etc/portage/emerge-ai.json` — JSON-объект; файл может содержать API-ключ,
права 0600 (при более широких — предупреждение). Без `endpoint` — явная
ошибка перед любым обращением к модели.

```json
{
  "endpoint": "http://127.0.0.1:8080/v1",
  "model": "qwen3.8-flash-next-unsloth-ud-q5_k_xl",
  "api_key": null,
  "language": "auto",
  "web_access": true,
  "llm_colors": {"content": "cyan", "reasoning": "dim", "question": "yellow"}
}
```

- `endpoint` — OpenAI-совместимый base URL (`/v1/chat/completions`).
- `model` — имя модели у провайдера.
- `language` — `auto` (из `LANG`/`LC_*`) либо явно (`russian`, `english`, ...).
- `web_access` — разрешён ли агенту веб-поиск при диагностике (по умолч. вкл).
- `llm_colors` — цвета блоков LLM-вывода (см. «Цвет вывода»); допустимы имена
  16 базовых цветов плюс `dim`/`bold`, а также `off`/`null` (выключить);
  невалидное имя — предупреждение и дефолт этого поля.

Неизвестные ключи игнорируются с предупреждением.

## Цвет вывода

- Цвет включается только когда целевой поток — TTY, `NO_COLOR` не задана и
  `TERM != dumb`; в pipe/файл/CI собственный вывод emerge-ai полностью plain,
  переопределения конфигурацией нет. Собственная окраска emerge передаётся
  как есть — коды ни добавляются, ни удаляются. Так как emerge запускается с
  захваченным выводом (и его auto-режим не увидел бы TTY), emerge-ai сам
  подставляет ему `--color=y`, когда цвет включён и пользователь не задал
  `--color` сам.
- Фиксированная палитра собственных сообщений (не настраивается): ошибки —
  красные, предупреждения — жёлтые, успешный итог — зелёный; строки risk-tier
  в дайджесте плана и doctor-отчёте — градиент от красного (tier 1) до
  приглушённого (высший tier); строки diff `+`/`-` — зелёный/красный;
  вопрос подтверждения — выделение.
- Блоки LLM (ответы модели при `-v`, proposal агента, digest `--changelog`)
  окрашиваются палитрой `llm_colors` (дефолты: `content` cyan, `reasoning`
  dim, `question` yellow). Строки, начинающиеся с `QUESTION:`, получают
  question-цвет — конвенция для вопросов модели оператору прямо в тексте;
  флаг `-v` по-прежнему управляет показом рассуждений и к цвету не относится.
- Промпты явно требуют от модели plain text без markdown; emerge-ai не
  рендерит markdown и не вычищает его из ответов постфактум.

## Восстановление (rollback)

Перед мержем очереди с tier 1–4 emerge-ai создаёт единую точку восстановления
на запуск: read-only btrfs-снапшот (`/.snapshots/emerge-ai/<run-id>`) либо,
если снапшот невозможен, tar-архив файлов из CONTENTS заменяемых пакетов в
`/var/lib/emerge-ai/archives/<run-id>/` (пользовательские данные `/home`,
`/root`, кэши в архив не попадают). После успешного мержа точки удаляются.
Если создать точку не удалось, а в очереди есть tier ≤4, мерж блокируется
(exit 5), если явно не согласоваться против этого.

Канал отката: разбор последствий → подтверждение → онлайн-восстановление;
при root в btrfs-подтоме выдаётся пошаговая инструкция с сохранением
снапшота/архива. `--i-understand-the-risks` подтверждает откат заранее.

## Дайджесты

- После успешного мерджа в stderr печатается дайджест запуска (собранные пакеты +
  действия агента). Опция конфига: `post_run_digest` (default true).
- `emerge-ai --changelog` — дайджест изменений: локальные новости, GLESA-индекс,
  GitHub releases (`gh_repos`), shallow-клоны (`git_urls`, кэш `/var/cache/emerge-ai/git`);
  при наличии `endpoint` список сокращает LLM до «самого важного», без него — raw-лист.

## Чек-лист ручной верификации на живом хосте (14.2, выполняет пользователь)

Полные команды — в `LIVE_CHECKS.md`; кратко:

- [ ] rest-tier полный цикл без снапшота: `sudo emerge-ai --ask app-misc/<мелкий-пакет>`
      → план+digest → подтверждение → мердж rc=0 → дайджест запуска, снапшот не создавался
      (`btrfs subvolume list /.snapshots | grep emerge-ai` пусто).
- [ ] критичный пакет на btrfs: `sudo emerge-ai --ask sys-apps/<критичный>`
      → снапшот `/.snapshots/emerge-ai/<run-id>` создался; после успеха — удалён;
      при откате-сценарии (`Ctrl+C` до завершения) инструкция восстановлена, снапшот жив.
- [ ] config-protect: пакет с конфигом → показ диффа, LLM-решение с цитатами,
      .pre-emerge-ai бэкап, ._cfg0000_ удалён только после «y».
- [ ] `--noninteractive`: rest-tier чинится сам, критичный — отказ с exit 6.
- [ ] `emerge-ai --changelog` — дайджест без падения при недоступных GitHub/git.
