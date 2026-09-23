# Fedora with systemd, for tests/from-zero.sh (DISTRO=fedora).
FROM fedora:latest
ENV container=podman
RUN dnf install -y -q systemd dbus-daemon python3 git sudo procps-ng fuse3 curl tar \
      glibc-langpack-en util-linux \
 && dnf clean all \
 && useradd -m -u 1000 -s /bin/bash -G wheel deck \
 && echo 'deck ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deck
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
