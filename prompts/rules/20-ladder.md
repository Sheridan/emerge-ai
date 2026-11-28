Fix escalation ladder (use the lowest sufficient level):
1. `/etc/portage/package.*` edits — `package.accept_keywords`, `package.use`,
   `package.mask`/`package.unmask`, `package.license` (accepted licenses) — with an audit
   comment `# aimerge: <date> <journal-id> <reason>`.
2. User patches in `/etc/portage/patches/<cat>/<pn>` when an upstream patch fixes a build.
3. aimerge overlay copy in `/var/lib/aimerge/overlay` (registry-managed) only when
   the package cannot build otherwise; record source, reason, journal-id.
Never edit the main trees (gentoo/guru/...); never delete overlay fixes automatically —
a tree-sync fix only triggers a removal *suggestion*.
