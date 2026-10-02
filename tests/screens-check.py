#!/usr/bin/env python3
"""phosphor screens checks: who's attached, and only a real deck client.

    python3 tests/screens-check.py

Verifies:
- WHO_RE parses `who -u`'s columns, with and without a remote address
- descendants() walks a real process tree (not just direct children)
- is_deck_client() only says yes for a `zellij ... attach <session>`
  descendant, matched on the real argv (a spawned process, not a mock)
- kick() reports failure instead of raising on a pid that's already gone
- kick() on a login whose pid isn't ours (sshd's monitor runs as root)
  signals its topmost descendant that is, and that one really ends
"""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import screens

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)


# 1. WHO_RE: with a remote address, and a local (no parens) login
m = screens.WHO_RE.match("you       pts/0        2026-09-22 11:07 00:05     1050101 (192.168.1.16)")
check("parses tty/idle/pid/from", m and m.group(2) == "pts/0" and m.group(5) == "00:05"
      and m.group(6) == "1050101" and m.group(7) == "192.168.1.16")
m2 = screens.WHO_RE.match("you       tty1         2026-09-22 09:00 .        12345")
check("local login (no parens) still parses", m2 and m2.group(7) is None)

def child_of(pid):
    """One /proc scan, no pgrep -- CI's slim image doesn't have procps."""
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == pid:
            continue
        try:
            stat = open("/proc/%s/stat" % p).read()
            if int(stat[stat.rindex(")") + 2:].split()[1]) == pid:
                return int(p)
        except (OSError, ValueError, IndexError):
            continue
    return None

# 2. descendants(): a real grandchild, not just a direct child
mid = subprocess.Popen(["sh", "-c", "sleep 30 & wait"])
time.sleep(0.3)
grandchild = child_of(mid.pid)
try:
    d = screens.descendants(mid.pid)
    check("includes self", mid.pid in d)
    check("includes the grandchild sleep, not just the shell", grandchild and grandchild in d)
finally:
    if grandchild:                  # or its sleep holds check.sh's $(...) open for 30s
        try:
            os.kill(grandchild, 9)
        except OSError:
            pass
    mid.kill(); mid.wait()

# 3. is_deck_client(): a real process whose argv says zellij attach <session>
fake = subprocess.Popen(["bash", "-c",
                         'exec -a zellij python3 -c "import time; time.sleep(30)" attach probe-session'])
try:
    time.sleep(0.3)
    check("matches a real zellij-attach-session argv", screens.is_deck_client(fake.pid, "probe-session"))
    check("does not match a different session name", not screens.is_deck_client(fake.pid, "other-session"))
finally:
    fake.kill(); fake.wait()

unrelated = subprocess.Popen(["sleep", "30"])
try:
    check("an unrelated process tree is never a deck client",
          not screens.is_deck_client(unrelated.pid, "probe-session"))
finally:
    unrelated.kill(); unrelated.wait()

# 4. kick(): a pid that's already gone fails cleanly, no traceback
gone = subprocess.Popen(["true"])
gone.wait()
ok, msg = screens.kick(gone.pid)
check("kicking a dead pid reports failure, doesn't raise", ok is False and msg)

# 5. kick() on a login we can't signal (who -u names sshd's root monitor):
# it ends our own topmost descendant instead. "Not ours" is faked for the
# top pid, since CI isn't root; the child really gets the signal.
top = subprocess.Popen(["sh", "-c", "sh -c 'sleep 30; :' & wait"])
try:
    mid = None
    for _ in range(50):
        mid = child_of(top.pid)
        if mid and child_of(mid):
            break
        time.sleep(0.05)
    notours = lambda p: p != top.pid and screens._mine(p)
    check("targets() picks the topmost pid that's ours, not the grandchild",
          screens.targets(top.pid, notours) == [mid])
    check("targets() is the pid itself when it's ours", screens.targets(top.pid) == [top.pid])
    check("nothing ours below: no targets", screens.targets(top.pid, lambda p: False) == [])
    ok, msg = screens.kick(top.pid, notours)
    check("kick through a root-owned login reports success", ok)
    top.wait(timeout=5)
    check("the kicked child really ended (and its parent with it)", top.returncode is not None)
finally:
    if top.poll() is None:
        top.kill(); top.wait()

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
