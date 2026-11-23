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

(заполняется по мере готовности инцидент-агента)

## Стенд оверлея (группа 11, тесты test_overlay_live.py)

Требуются на машине (уже созданы):
- `/etc/portage/repos.conf/emerge-ai-test.conf` (prio 99) и `emerge-ai-test-base.conf` (prio 50)
- `/var/db/repos/emerge-ai-test{,-base}` (sheridan:portage) c `profiles/repo_name`,
  `metadata/layout.conf` (masters=gentoo), `profiles/categories` (`ea-test`)
- dummy `ea-test/foo-1.0` в обоих, Manifest генерирует `overlay.write_manifest`
- реестр `/var/db/repos/emerge-ai-test/registry.json` (journal_id `live-11.2`)

Проверка: `ACCEPT_KEYWORDS="~amd64" emerge -p -v "=ea-test/foo-1.0"` →
`[ebuild N ] ea-test/foo-1.0::emerge-ai-test`.
