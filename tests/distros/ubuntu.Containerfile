# Ubuntu 24.04 with systemd, for tests/from-zero.sh (DISTRO=ubuntu).
FROM ubuntu:24.04
ENV container=podman DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      systemd systemd-sysv dbus libpam-systemd dbus-user-session \
      curl ca-certificates python3 git sudo procps fuse3 locales \
 && rm -rf /var/lib/apt/lists/* \
 && (userdel -r ubuntu 2>/dev/null || true) \
 && useradd -m -u 1000 -s /bin/bash -G sudo deck \
 && echo 'deck ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deck \
 && systemctl mask systemd-firstboot.service systemd-resolved.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
