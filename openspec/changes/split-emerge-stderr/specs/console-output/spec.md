# Spec Delta

## Purpose

Гарантирует, что при захвате вывода emerge его stderr не подмешивается в stdout emerge-ai: потоки emerge маршрутизируются в одноимённые потоки emerge-ai, а общий буфер для enrichment/incident сохраняется.

## ADDED Requirements

### Requirement: Разделение stdout и stderr emerge при захвате

При запуске emerge с захваченным выводом emerge-ai SHALL направлять строки stdout emerge в собственный stdout, а строки stderr emerge — в собственный stderr, без изменений байт в байт (включая ANSI-коды emerge). stdout emerge-ai SHALL содержать только stdout emerge: stderr-строки emerge в нём появляться не SHALL. Для нужд incident и enrichment emerge-ai SHALL сохранять объединённый буфер обеих сторон; порядок строк из разных потоков в этом буфере не нормируется.

#### Scenario: stderr не течёт в stdout
- **WHEN** emerge в захваченном прогоне пишет различимые строки в stdout и stderr, а stdout emerge-ai перенаправлен в файл
- **THEN** в файле только stdout-строки emerge; stderr-строки emerge отсутствуют

#### Scenario: stderr доходит до stderr
- **WHEN** emerge пишет предупреждение в stderr при `emerge-ai -av 1>/dev/null`
- **THEN** предупреждение видно во stderr emerge-ai без изменений

#### Scenario: Буфер для инцидента полный
- **WHEN** сбойный прогон печатал текст в оба потока emerge
- **THEN** описание инцидента и enrichment содержат строки обеих сторон, код возврата emerge не изменён

#### Scenario: ANSI в stderr сохраняется
- **WHEN** крашеный вывод emerge содержит ANSI-коды в stderr-строках и вывод идёт в цветной TTY
- **THEN** в stderr emerge-ai эти ANSI-коды передаются без изменений (окраска — политика console-output в части неэкранируемого вывода emerge)
