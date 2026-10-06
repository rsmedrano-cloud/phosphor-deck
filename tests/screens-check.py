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
- said() reads the kind off a real `phosphor attach --screen KIND` argv
- change() / moving(): o on a kind's own deck shares it, on a screen that
  says a kind with no block gives it one, on one that says none does nothing
- retype() adds and takes out [screens.KIND] in a temp profile, with a
  backup, without running a real gen
"""
import os, signal, subprocess, sys, time

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
# Off check.sh's pipe and in a group of its own: the kick orphans the sleep,
# which otherwise held that pipe open for its whole 30s.
top = subprocess.Popen(["sh", "-c", "sh -c 'sleep 30; :' & wait"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
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
    try: os.killpg(top.pid, signal.SIGKILL)
    except OSError: pass
    top.wait()

# 6. said(): the kind on a real attach argv, '' with none
sk = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)", "attach", "--screen", "phone"])
plain = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)", "attach"])
try:
    time.sleep(0.3)
    check("said() reads --screen KIND off the attach argv", screens.said(sk.pid) == "phone")
    check("said() is empty for a screen that says no kind", screens.said(plain.pid) == "")
finally:
    for p_ in (sk, plain):
        p_.kill(); p_.wait()

# 7. change() and moving()
rows = [{"pid": 1, "session": "deck-tablet", "said": "tablet"},
        {"pid": 2, "session": "deck", "said": "phone"},
        {"pid": 3, "session": "deck", "said": ""},
        {"pid": 4, "session": "deck", "said": "phone"},
        {"pid": 5, "session": "deck-tablet", "said": "tablet"}]
have = {"tablet": {}}
check("o on a kind's own deck shares it", screens.change(rows[0], have, "deck") == ("share", "tablet"))
check("o on a screen saying a kind without a block gives it one",
      screens.change(rows[1], have, "deck") == ("own", "phone"))
check("o on a screen saying no kind does nothing", screens.change(rows[2], have, "deck")[0] is None)
check("o on a screen saying a kind that can't be one does nothing",
      screens.change({"pid": 6, "session": "deck", "said": "my-tablet"}, have, "deck")[0] is None)
check("o on a kind that just got a block waits for its reconnect",
      screens.change(rows[1], {"phone": {}}, "deck")[0] is None)
check("sharing moves every screen of that kind's deck",
      [r["pid"] for r in screens.moving(rows, "share", "tablet", "deck")] == [1, 5])
check("a deck of its own moves every screen saying that kind",
      [r["pid"] for r in screens.moving(rows, "own", "phone", "deck")] == [2, 4])

# 8. retype(): into a temp profile, gen faked
import tempfile
tmp = tempfile.mkdtemp()
prof = os.path.join(tmp, "deck.toml")
open(prof, "w").write('[deck]\nsession = "deck"\n\n[screens.tablet]\ntabs = ["SYS"]\n\n[keys]\nedit = "Alt r"\n')
os.environ["PHOSPHOR_PROFILE"] = prof
import deckconf
ok, _ = screens.retype("own", "phone", gen=lambda: True)
p = deckconf.tomllib.loads(open(prof).read())
check("own adds [screens.phone], every tab", ok and p["screens"].get("phone") == {})
check("own keeps the other kinds and tables", "tablet" in p["screens"] and p["keys"]["edit"] == "Alt r")
check("a backup of the profile as it was", os.path.exists(prof + ".bak")
      and "phone" not in open(prof + ".bak").read())
ok, _ = screens.retype("share", "tablet", gen=lambda: True)
p = deckconf.tomllib.loads(open(prof).read())
check("share takes [screens.tablet] out, the rest stays",
      ok and "tablet" not in p["screens"] and "phone" in p["screens"] and p["keys"]["edit"] == "Alt r")
ok, m = screens.retype("own", "phone", gen=lambda: True)
check("a block that's already there isn't written twice", not ok
      and open(prof).read().count("[screens.phone]") == 1)
ok, m = screens.retype("own", "eink", gen=lambda: False)
check("a failed gen is reported, not hidden", not ok and "gen" in m)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
