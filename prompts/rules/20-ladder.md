Fix escalation ladder (use the lowest sufficient level):
1. `/etc/portage/package.*` keywords/masks/use/accept_license — with an audit comment
   `# emerge-ai: <date> <journal-id> <reason>`.
2. User patches in `/etc/portage/patches/<cat>/<pn>` when an upstream patch fixes a build.
3. emerge-ai overlay copy in `/var/lib/emerge-ai/overlay` (registry-managed) only when
   the package cannot build otherwise; record source, reason, journal-id.
Never edit the main trees (gentoo/guru/...); never delete overlay fixes automatically —
a tree-sync fix only triggers a removal *suggestion*.
