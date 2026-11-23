# Tasks

## 1. Подстановка флага

- [x] 1.1 `runner.with_color_flag(args, stream=None)`: TTY-цвет → `--color=y` в начало, иначе без изменений; пользовательский `--color` (или `--color=...`) отключает подстановку; подключить в `run_emerge_capturing` перед Popen; unit-тесты в `tests/test_runner.py` (tty/pipe/NO_COLOR/пользовательский флаг)
- [x] 1.2 Интеграция: через `emerge_stub` проверить argv с подставленным `--color=y` при monkeypatch-isatty stdout и отсутствие подстановки под capsys; полный pytest зелёный

## Workflow follow-up

- Валидация, ревью, архив по правилам проекта.
