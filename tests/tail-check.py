#!/usr/bin/env python3
"""phosphor tail HOST [SERVICE]: journalctl/docker/podman, filled in, through
the same phosphor run --reconnect a normal ssh tab already uses.

    python3 tests/tail-check.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import tail

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# remote_argv(): journalctl by default, docker/podman when asked, systemd/
# is just the explicit spelling of the default
check("no service: plain journalctl", tail.remote_argv(None) ==
      ["journalctl", "-f", "-n", "100"])
check("bare name: journalctl -u", tail.remote_argv("nginx") ==
      ["journalctl", "-f", "-n", "100", "-u", "nginx"])
check("systemd/name: same as bare", tail.remote_argv("systemd/nginx") ==
      tail.remote_argv("nginx"))
check("docker/name", tail.remote_argv("docker/jellyfin") ==
      ["docker", "logs", "-f", "--tail", "100", "jellyfin"])
check("podman/name", tail.remote_argv("podman/jellyfin") ==
      ["podman", "logs", "-f", "--tail", "100", "jellyfin"])
check("an unrecognized kind/ prefix still tries journalctl -u on the name part",
      tail.remote_argv("weird/thing") == ["journalctl", "-f", "-n", "100", "-u", "thing"])

PROF = {"hosts": [
    {"name": "brain", "role": "brain", "local": True},
    {"name": "db-box", "role": "storage", "ssh": "db-box-alias", "user": "deploy"},
    {"name": "nimbus", "role": "desktop"},
]}

check("finds a host by name", tail.find_host(PROF, "db-box")["ssh"] == "db-box-alias")
check("unknown host: None", tail.find_host(PROF, "nope") is None)

# main(): never actually execs a real process here -- os.execv is patched
real_execv = tail.os.execv
calls = []
def fake_execv(path, argv):
    calls.append(argv)
tail.os.execv = fake_execv
real_load = tail.deckconf.load
tail.deckconf.load = lambda: (PROF, "t")

def run(argv):
    saved = sys.argv
    sys.argv = ["phosphor-tail"] + argv
    try:
        return tail.main()
    finally:
        sys.argv = saved

try:
    calls.clear()
    rc = run(["nope-a-host"])
    check("unknown host: exits 1, never execs anything", rc == 1 and calls == [])

    calls.clear()
    run(["db-box", "nginx"])
    check("execs through phosphor run --reconnect", calls and "run" in calls[0] and "--reconnect" in calls[0])
    check("ssh -t to the resolved target, not the bare host name",
          calls[0][calls[0].index("--") + 1:] == ["ssh", "-t", "deploy@db-box-alias",
                                                    "journalctl", "-f", "-n", "100", "-u", "nginx"])

    calls.clear()
    run(["brain"])
    check("the local host skips ssh entirely",
          calls[0][calls[0].index("--") + 1:] == ["journalctl", "-f", "-n", "100"])

    calls.clear()
    run(["nimbus", "docker/jellyfin"])
    check("a host with no explicit user/ssh alias falls back to its own name",
          calls[0][calls[0].index("--") + 1:] == ["ssh", "-t", "nimbus",
                                                    "docker", "logs", "-f", "--tail", "100", "jellyfin"])
finally:
    tail.os.execv = real_execv
    tail.deckconf.load = real_load

if fails:
    print("tail-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("tail-check ok")
