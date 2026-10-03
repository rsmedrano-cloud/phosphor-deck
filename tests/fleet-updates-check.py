#!/usr/bin/env python3
"""fleet updates: collect.sh counts a host's pending updates (and how many
are security ones) in the background, from the package manager's own
cache, never with its lock, and only again once the package database
changes or 6 hours pass. Run with fake apt-get/dnf/apk/checkupdates on a
PATH holding nothing else of the kind, never the real ones; then the card
and glance.

    python3 tests/fleet-updates-check.py
"""
import os, shutil, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import fleet, health

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

TOOLS = ("sh awk find grep mkdir mv rm wc sort cat sleep df tail id ls "
         "printf sed tr head touch").split()

def fake_path(fakes):
    """A bin folder with the plain tools collect.sh needs and the fake
    package managers in `fakes` ({name: script body}), each logging its
    arguments: no real package manager is ever reachable."""
    b = tempfile.mkdtemp()
    for t in TOOLS:
        p = shutil.which(t)
        if p:
            os.symlink(p, os.path.join(b, t))
    log = os.path.join(b, "calls")
    for name, body in fakes.items():
        f = os.path.join(b, name)
        open(f, "w").write('#!/bin/sh\necho "%s $*" >> %s\n%s\n' % (name, log, body))
        os.chmod(f, 0o755)
    return b, log

def run(path, run_dir, pkgroot):
    env = dict(os.environ, PATH=path, XDG_RUNTIME_DIR=run_dir, PHOSPHOR_PKGROOT=pkgroot,
               PHOSPHOR_SYS=tempfile.mkdtemp())
    r = subprocess.run(["sh", os.path.join(ROOT, "share", "collect.sh")],
                       capture_output=True, text=True, env=env, timeout=30)
    return [l for l in r.stdout.splitlines() if l.startswith("UPD=")]

def settle(run_dir):
    """Wait for the background count to finish."""
    for _ in range(100):
        if not os.path.exists(os.path.join(run_dir, "phosphor-updates.run")):
            return
        time.sleep(0.1)

def calls(log):
    return open(log).read().splitlines() if os.path.exists(log) else []

def counted(fakes):
    """(first poll's UPD lines, second poll's) for a fresh host."""
    path, _ = fake_path(fakes)
    rd = tempfile.mkdtemp()
    first = run(path, rd, tempfile.mkdtemp())
    settle(rd)
    return first, run(path, rd, tempfile.mkdtemp())

# apt: Inst lines, the ones from a -security suite counted apart
APT = """case "$*" in *-s*) ;; *) exit 9 ;; esac
cat <<'X'
NOTE: This is only a simulation!
Inst base-files [12.4] (12.5 Debian:12.5/stable [amd64])
Inst liblzma5 [5.4.1-1] (5.4.1-2 Debian-Security:12/stable-security [amd64])
Inst openssl [3.0.11-1] (3.0.11-2 Debian-Security:12/stable-security [amd64])
Conf base-files (12.5 Debian:12.5/stable [amd64])
X"""
path, log = fake_path({"apt-get": APT})
rd, pkg = tempfile.mkdtemp(), tempfile.mkdtemp()
os.makedirs(pkg + "/var/lib/dpkg")
open(pkg + "/var/lib/dpkg/status", "w").write("")
check("the first poll doesn't wait for the count", run(path, rd, pkg) == [])
settle(rd)
check("apt: 3 pending, 2 security", run(path, rd, pkg) == ["UPD=3|2"])
c = calls(log)
check("apt is only ever simulated, without its lock",
      len(c) == 1 and "-s" in c[0].split() and "Debug::NoLocking=1" in c[0])
run(path, rd, pkg); settle(rd)
check("a fresh count isn't counted again", len(calls(log)) == 1)
cache = os.path.join(rd, "phosphor-updates")
old = time.time() - 60
os.utime(cache, (old, old))
os.utime(pkg + "/var/lib/dpkg/status", None)
run(path, rd, pkg); settle(rd)
check("an upgrade (dpkg's status changed) counts again", len(calls(log)) == 2)
old = time.time() - 7 * 3600
os.utime(cache, (old, old))
os.utime(pkg + "/var/lib/dpkg/status", (old - 60, old - 60))
run(path, rd, pkg); settle(rd)
check("6 hours later it counts again", len(calls(log)) == 3)

# dnf: from its cache only (-C); exit 100 means updates
DNF = """case "$*" in
  *check-update*) printf 'bash.x86_64  5.2.26-3.fc40  updates\\nvim.x86_64  9.1-1.fc40  updates\\n'; exit 100 ;;
  *updateinfo*) printf 'FEDORA-2024-1 Important/Sec. bash-5.2.26-3.fc40.x86_64\\nFEDORA-2024-2 Moderate/Sec. bash-5.2.26-3.fc40.x86_64\\n' ;;
esac"""
first, second = counted({"dnf": DNF})
check("dnf: 2 pending, 1 security (one package, two advisories)", second == ["UPD=2|1"])
path, log = fake_path({"dnf": DNF})
rd = tempfile.mkdtemp(); run(path, rd, tempfile.mkdtemp()); settle(rd)
check("dnf never leaves its cache", all(" -C " in l for l in calls(log)))
_, second = counted({"dnf": "exit 1"})
check("a dnf that fails says nothing, not 0", second == [])

# apk: no security split
_, second = counted({"apk": "printf 'Installed:                                Available:\\nbusybox-1.36.1-r1        < 1.36.1-r2\\n'"})
check("apk: 1 pending, security unknown", second == ["UPD=1|"])

# Arch: checkupdates, and arch-audit when it's there
CU = "printf 'linux 6.9.1 -> 6.9.2\\nopenssl 3.3.0 -> 3.3.1\\n'"
_, second = counted({"checkupdates": CU})
check("checkupdates: 2 pending, security unknown", second == ["UPD=2|"])
_, second = counted({"checkupdates": CU, "arch-audit": "echo openssl"})
check("with arch-audit: 1 of them security", second == ["UPD=2|1"])
_, second = counted({})
check("no package manager known: no line", second == [])

# what the deck makes of it
check("parse", health.updates({"UPD": "3|2"}) == (3, 2))
check("security unknown", health.updates({"UPD": "4|"}) == (4, None))
check("garbled says nothing", health.updates({"UPD": "x|y"}) is None)
base = {"ok": True, "CPU": 3, "MEMU": 100, "MEMT": 1000}
_, body = fleet.card("host", 40, dict(base, UPD="3|2"))
check("the card calls out security updates", any("2 security updates" in b for b in body))
_, body = fleet.card("host", 40, dict(base, UPD="4|"))
check("plain updates show, quieter", any("4 updates" in b for b in body))
_, body = fleet.card("host", 40, dict(base, UPD="0|0"))
check("nothing pending, nothing shown", not any("update" in b for b in body))
check("glance flags security updates", health.sensor_problems(dict(base, UPD="5|1")) == ["1 security update"])
check("glance leaves plain updates alone", health.sensor_problems(dict(base, UPD="5|0")) == [])
check("nor unknown security", health.sensor_problems(dict(base, UPD="5|")) == [])

if fails:
    print("\n".join("FAIL: " + f for f in fails))
    sys.exit(1)
print("ok")
