# Arch Linux with systemd, for tests/from-zero.sh (DISTRO=arch).
FROM archlinux:latest
ENV container=podman
RUN pacman -Syu --noconfirm --needed systemd dbus python git sudo procps-ng fuse3 curl tar \
 && pacman -Scc --noconfirm \
 && useradd -m -u 1000 -s /bin/bash -G wheel deck \
 && echo 'deck ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deck
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
