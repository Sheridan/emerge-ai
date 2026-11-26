# Tasks

## 1. Детектор (`triage.py`, новый модуль)

- [x] 1.1 Маркерный словарь каналов portage: `!!!`, `WARNING: ... skipped due to ...`,
      ` * IMPORTANT: config file ... needs updating`, `!!! Problems have been
      detected with your world file`, структурные строки `conflicts with`,
      `required by`, `masked by:`; dataclass `Finding(kind, cpv|atom, evidence,
      line_no)`; чистая функция `scan(text, argv_flags) -> Verdict(clean|degraded,
      findings)`.
- [x] 1.2 Форменные флаги: запрос обновления (`-u`/`-D`/`-N` в argv) при
      `Total: 0 packages` → находка `empty-update`; парсинг строки `Total: N
      packages` (рядом с `digest.EBUILD_LINE_RE`).
- [x] 1.3 `build_slice(text, cap_bytes)`: строки маркеров + окно контекста,
      слияние перекрывающихся окон, строка `Total:`, плашка `[capped; полный
      текст: <path>]`; cap — несколько KB константой модуля.
- [x] 1.4 Юниты на живых фикстурах (взять реальный вывод прогона
      `@world -uDN --keep-going -av`): конфликт edk2-bin/qemu, yazi+
      `masked by: ~amd64 keyword`, world-файл, IMPORTANT config, чистый план,
      переполнение капа, USE-простыни не попадают в срез.

## 2. Проводка в план-фазе (`cli.py`)

- [x] 2.1 Запись `plan-output.txt` (ANSI-снятый буфер помпов) в директорию
      прогона на каждой план-фазе, включая «чисто».
- [x] 2.2 Вызов `triage.scan` после план-фазы при `rc == 0`; вердикт и
      находки — в состояние прогона; при `rc != 0` поведение не меняется
      (штатный `_incident_flow`).
- [x] 2.3 Печать отчёта в мутационных ветках (обычная и `-a`) после дайджеста,
      до `Proceed?`/protect/merge; stdout emerge и коды выхода не меняются.

## 3. контракт дайджеста (`enrich.py`, `prompts.py`)

- [x] 3.1 Вход `summarize_plan`: план-дайджест + severity-срез (блок
      `[severity-slice]` в промпте).
- [x] 3.2 Structured output: `{summary, findings[]}` в существующей схеме
      `try_structured`; schema-failure → сводка отсутствует, поток и
      детерминированные находки не затронуты.
- [x] 3.3 Инструкция сводке при деградации: поимённо пропущенные пакеты и
      причины вместо констатации пустого плана.

## 4. Advisory-отчёт

- [x] 4.1 `triage.render_report(verdict, findings, candidate_lines)` — общий
      рендерер для `-p` и мутационных режимов; кандидат-строки только из
      исполняемых сейчас видов apply-канала (`config_edit` kinds, etcupdate);
      не-исполняемые починки — строка «система это пока не исполнит».
- [x] 4.2 `-p` при вердикте degraded: `IncidentAgent` с классом
      `plan-degraded` в read-only песочнице (без `ask_operator`), отчёт с
      объяснениями; чистый план — agent не запускается.
- [x] 4.3 Без endpoint / сбой LLM: детерминированная часть отчёта печатается;
      deep-разбор в `-p` без endpoint не запускается.

## 5. Инцидент `plan-degraded`

- [x] 5.1 `incident.py`: FAILURE_CLASSES-запись `plan-degraded`; для класса —
      `log_path` на `plan-output.txt`, без `stderr_tail[-4000:]` усечения.
- [x] 5.2 `agent.py`: `CLASS_SKELETONS["plan-degraded"]`; `grep_log`/
      `read_file_window` получают путь `plan-output.txt` в доступных логах.

## 6. Интеграционные тесты

- [x] 6.1 Живой кейс на stub-emerge (rc 0, edk2/yazi/world): `-p` — отчёт с
      кандидатами, ноль вопросов, код 0, /etc не тронут; `-a` — отчёт до
      `Proceed?`, «y» мерджит как раньше без починок.
- [x] 6.2 Чистый план: ровно один LLM-вызов (дайджест), отчёт отсутствует,
      тайминг-ассертов не добавляем — ассерт «IncidentAgent не конструировался».
- [x] 6.3 Деградация без endpoint: детерминированный отчёт, `Proceed?` штатно.
