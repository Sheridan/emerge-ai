Risk tiers for every package you touch (single source of truth is the tier service):
1 boot-critical (kernel, glibc, openrc/systemd-core, baselayout, busybox, grub...):
   can make the system unbootable.
2 shell/core-utils (bash, coreutils, util-linux, findutils, tar, zlib...).
3 network-remote (sshd, openssh, net-mgmt critical, systemd-networkd): can lock out SSH.
4 GUI/desktop (xorg, wayland, display manager, drivers): can break the graphical login.
5 everything else.
When unsure between two tiers, choose the lower (more conservative) number.
