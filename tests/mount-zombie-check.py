#!/usr/bin/env python3
"""~/fleet mounts don't recover from a zombie transport (issue #31): a
remote sleeping or changing IP over Tailscale can leave the rclone sftp
mount registered with the kernel (os.path.ismount() still says "mounted")
while every real access fails with ENOTCONN ('Transport endpoint is not
connected'). Nothing noticed or fixed this before -- fleet.py now sweeps
for it in the background and recovers with fusermount -uz + a unit
restart.

    python3 tests/mount-zombie-check.py
"""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import dlog
import deckconf
import fleet

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

dlog.DIR = tempfile.mkdtemp()
dlog.LOG = os.path.join(dlog.DIR, "deck.log")
def logged():
    return open(dlog.LOG).read() if os.path.exists(dlog.LOG) else ""

# mount_zombie(): only the specific ENOTCONN error counts, and it never
# blocks past its own timeout on something merely slow.
real_run = subprocess.run
def fake_run_ok(cmd, **kw): return subprocess.CompletedProcess(cmd, 0, "", "")
def fake_run_notconn(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 1, "", "stat: cannot stat 'x': Transport endpoint is not connected\n")
def fake_run_other_error(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 1, "", "stat: cannot stat 'x': No such file or directory\n")
def fake_run_timeout(cmd, **kw): raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

deckconf.subprocess.run = fake_run_ok
check("a healthy mount isn't a zombie", deckconf.mount_zombie("/fake/mp") is False)
deckconf.subprocess.run = fake_run_notconn
check("ENOTCONN's exact message is a zombie", deckconf.mount_zombie("/fake/mp") is True)
deckconf.subprocess.run = fake_run_other_error
check("a different stat error is NOT a zombie (e.g. not mounted at all)",
      deckconf.mount_zombie("/fake/mp") is False)
deckconf.subprocess.run = fake_run_timeout
check("a stat that hangs past its timeout is treated as merely slow, not dead",
      deckconf.mount_zombie("/fake/mp") is False)
deckconf.subprocess.run = real_run

# mount_hosts(): the same filter gen.py's Ctx.remotes() wires fleet-*.service
# from -- non-local hosts with `mount` set, nothing else.
prof = {"hosts": [
    {"name": "brain", "local": True, "mount": "/home"},
    {"name": "viewer", "role": "viewer"},
    {"name": "storage", "mount": "/mnt/data"},
    {"name": "no-mount-host"},
]}
names = [h["name"] for h in deckconf.mount_hosts(prof)]
check("only a non-local host with mount set qualifies", names == ["storage"])

# recover_zombie_mount(): fusermount -uz the mountpoint, then restart its
# unit -- in that order, since a fresh rclone can't mount over one the
# kernel still considers busy from the dead process.
calls = []
def fake_recover_run(cmd, **kw):
    calls.append(cmd)
    return subprocess.CompletedProcess(cmd, 0, "", "")
fleet.subprocess.run = fake_recover_run
try:
    ok = fleet.recover_zombie_mount("storage", "/home/x/fleet/storage")
finally:
    fleet.subprocess.run = real_run
check("recover_zombie_mount() reports success", ok is True)
check("fusermount -uz runs against the mountpoint",
      any(c[0].endswith(("fusermount", "fusermount3")) and "-uz" in c and c[-1] == "/home/x/fleet/storage"
          for c in calls))
check("only after that does it restart the host's own unit",
      calls[1] == ["systemctl", "--user", "restart", "fleet-storage.service"])

# mount_sweep(): a zombie among healthy mounts gets recovered, and the
# sweep never leaks which host into deck.log (same rule as collect()).
real_zombie, real_recover = deckconf.mount_zombie, fleet.recover_zombie_mount
def fake_zombie(mp): return mp.endswith("dead-host-example")
def fake_recover(name, mp): return True
deckconf.mount_zombie, fleet.recover_zombie_mount = fake_zombie, fake_recover
try:
    n = fleet.mount_sweep(["alive-host-example", "dead-host-example"], "/home/x/fleet")
finally:
    deckconf.mount_zombie, fleet.recover_zombie_mount = real_zombie, real_recover
check("the sweep recovers exactly the zombie one", n == 1)
check("a real hostname never lands in deck.log", "dead-host-example" not in logged()
      and "alive-host-example" not in logged())
check("the sweep does log that something happened, generically", "zombie-mount" in logged())

# A sweep that finds nothing zombie logs nothing at all.
open(dlog.LOG, "w").close()
deckconf.mount_zombie = lambda mp: False
try:
    n = fleet.mount_sweep(["alive-host-example"], "/home/x/fleet")
finally:
    deckconf.mount_zombie = real_zombie
check("nothing to recover: nothing logged", n == 0 and logged() == "")

# mount_watchdog() is a no-op with no mounted hosts at all -- returns
# instead of looping/sleeping forever for a profile with none.
check("no mount hosts: mount_watchdog() returns instead of looping",
      fleet.mount_watchdog([], "/home/x/fleet") is None)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
