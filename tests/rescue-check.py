#!/usr/bin/env python3
"""The recovery screen (lib/rescue.py): when the deck won't start, `deck`
says why and offers the fixes, instead of zellij's "No session found".

    python3 tests/rescue-check.py

- reading: systemctl show's text, zellij's panics (only since the last
  start), which processes hold a start up (by their argv), how each state
  is said, and doctor's two new lines (a start hung for minutes, a panic
  since the last start)
- the screen at a phone's width: nothing wider than it, every option and
  every holder tappable
- deck-up: PHOSPHOR_WEB=0 makes one start without browser access (a real
  run of the generated script, with a zellij that writes down its argv)
- the screen itself, in a pty, with a systemctl that only writes down what
  it was asked: 1 closes that holder (a real process), r closes the hung
  start and restarts deck.service, w does it with PHOSPHOR_WEB=0 set and
  unset again, and the screen goes in once the deck is up; q leaves
Nothing here touches a real deck: the session is probe-rescue, the
processes are this test's own.
"""
import os, pty, re, select, subprocess, sys, tempfile, termios, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import rescue, doctor, gen
from ui import uncolor, vlen, BAD, WARN

fails = []
def check(what, ok):
    print("  %s %s" % ("ok  " if ok else "FAIL", what))
    if not ok: fails.append(what)

SESS = "probe-rescue"
tmp = tempfile.mkdtemp()
now = time.time()

# 1. systemctl show
mono = 100000.0
st = rescue.parse_show("ActiveState=activating\nSubState=start\nResult=success\nExecMainStatus=0\n"
                       "StateChangeTimestampMonotonic=%d\nInactiveExitTimestampMonotonic=%d\n"
                       % ((mono - 4 * 3600) * 1e6, (mono - 4 * 3600) * 1e6), now, mono)
check("show: state and since", st["state"] == "activating" and abs(st["since"] - (now - 4 * 3600)) < 1)
check("show: a timestamp of 0 is never", rescue.parse_show("ActiveState=inactive\n"
      "StateChangeTimestampMonotonic=0\n", now, mono)["since"] is None)
st["timer"] = "active"
sym, say = rescue.describe(st, now)
check("a start hung for hours is bad, and says how long", sym == BAD and "4h" in say)
sym, _ = rescue.describe(dict(st, since=now - 20), now)
check("a start of 20s is only starting", sym == WARN)
_, say = rescue.describe(dict(st, state="failed", result="timeout"), now)
check("a failed start says it timed out", "timed out" in say)
_, say = rescue.describe(dict(st, state="inactive", timer="inactive"), now)
check("stopped with its watchdog says so", "watchdog" in say)
check("no user systemd says so", "systemd" in rescue.describe(None, now)[1])

# 2. zellij's panics
def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + ".123"
LOGTEXT = "\n".join([
    "INFO   |zellij_server            | %s [main      ] zellij-server/src/lib.rs:864: Starting Zellij server! " % stamp(now - 7200),
    "ERROR  |zellij_utils::errors::not| %s [main      ] zellij-utils/src/errors.rs:850: Panic occurred:" % stamp(now - 7200),
    "             thread: main",
    "             location: At zellij-server/src/pty.rs:1355:30",
    "             message: Program terminates: a fatal error occurred ",
    "ERROR  |zellij_utils::errors::not| %s [main      ] zellij-utils/src/errors.rs:850: Panic occurred:" % stamp(now - 60),
    "             thread: main",
    "             location: At zellij-server/src/lib.rs:1462:26",
    "             message: called `Option::unwrap()` on a `None` value ",
    "ERROR  |zellij_utils::errors::not| %s [stdin_pump] zellij-utils/src/errors.rs:850: Panic occurred:" % stamp(now - 30),
    "             thread: stdin_pump",
    "             location: At zellij-client/src/os_input_output.rs:211:47",
    "             message: called `Result::unwrap()` on an `Err` value: Os { code: 5 } ",
    "ERROR  |zellij_client            | %s [main      ] Failed to start web server: Address in use" % stamp(now - 59),
])
p = rescue.panics(LOGTEXT)
check("both of the server's panics read, a client's left out", len(p) == 2)
check("a panic says where and what", p[-1][1] == "lib.rs:1462:26: called `Option::unwrap()` on a `None` value")
check("only panics since the last start", len(rescue.panics(LOGTEXT, now - 600)) == 1)
check("no log, no panics", rescue.panics("") == [] and rescue.log_tail(os.path.join(tmp, "none")) == "")

# 3. what holds a start up, by argv
Z = "/home/x/.local/bin/zellij"
W = {
    "a start that never finished": [Z, "--layout", SESS, "attach", "--create-background", SESS, "options", "--web-sharing", "on"],
    "the browser-access server": [Z, "web", "--start", "--daemonize"],
    "a screen still attached to the old deck": [Z, "attach", SESS],
    "a screen's reconnect loop": ["bash", "-c", "deck --screen phone || zellij attach " + SESS],
    "another screen waiting to get in": ["python3", "/home/x/phosphor-deck/phosphor", "attach", "--screen", "phone"],
}
for want, argv in W.items():
    check("argv: " + want, rescue.what(argv, SESS) == want)
check("argv: the deck's own server isn't one", rescue.what([Z, "--server", "/run/user/1/zellij/x/" + SESS], SESS) is None)
check("argv: another session's start isn't one",
      rescue.what([Z, "attach", "--create-background", "other"], SESS) is None)
check("argv: any other shell isn't one", rescue.what(["bash", "-c", "make deck"], SESS) is None)
check("argv: phosphor doctor isn't one", rescue.what(["python3", "/x/phosphor", "doctor"], SESS) is None)

# 4. holders(): a real process, found and closed; one we run under, left out
fake = subprocess.Popen(["bash", "-c", 'exec -a zellij python3 -c "import time; time.sleep(60)" attach --create-background %s' % SESS])
time.sleep(0.3)
found = [h for h in rescue.holders(SESS) if h[0] == fake.pid]
check("holders: a hung start found, with since", found and found[0][1] == "a start that never finished"
      and found[0][2] and abs(found[0][2] - time.time()) < 30)
check("holders: what this runs under is left out", not [h for h in rescue.holders(SESS, me=fake.pid) if h[0] == fake.pid])
rescue.close([fake.pid], wait=2)
check("close: it's gone", fake.wait(timeout=5) is not None)

# 5. the screen at a phone's width
held = [(1, "a start that never finished", now - 4 * 3600), (2, "a screen's reconnect loop", now - 60),
        (3, "the browser-access server", None)]
for w in (40, 80):
    out, taps = rescue.lines(SESS, st, p, held, True, w, now)
    check("width %d: nothing wider" % w, all(vlen(l) <= w for l in out))
    keys = set(taps.values())
    check("width %d: every option and holder tappable" % w, {"r", "w", "k", "l", "d", "s", "q", "1", "2", "3"} <= keys)
    check("width %d: a tap's row shows its key" % w,
          all(uncolor(out[r - 1]).lstrip().startswith(k) or k.isdigit() for r, k in taps.items()))
out, taps = rescue.lines(SESS, st, [], [], False, 80, now)
check("no web, no holders: no w, no k", not {"w", "k"} & set(taps.values()))

# 6. doctor
rows = doctor.deck_start(SESS, st=dict(st, started=now - 600), log=LOGTEXT, now=now)
check("doctor: a start hung for hours is a blocker", any(r[0] == BAD and "starting for 4h" in r[2] for r in rows))
check("doctor: a panic since the last start", any(r[1] == "zellij panic" and "1 since" in r[2] for r in rows))
check("doctor: a start that went fine says nothing",
      doctor.deck_start(SESS, st=dict(st, state="inactive", started=now - 30), log=LOGTEXT, now=now) == [])

# 7. deck-up: PHOSPHOR_WEB=0 is one start without browser access
bin_ = os.path.join(tmp, "bin"); os.makedirs(bin_)
ZLOG = os.path.join(tmp, "zellij-argv")
open(os.path.join(bin_, "zellij"), "w").write('#!/bin/sh\necho "$@" >> %s\n' % ZLOG)
os.chmod(os.path.join(bin_, "zellij"), 0o755)
up = os.path.join(tmp, "up.sh")
open(up, "w").write(gen.DECK_UP % {"zellij": os.path.join(bin_, "zellij"), "session": SESS, "web": "1",
                                   "python": "true", "repo": tmp})
def ran(env):
    try: os.unlink(ZLOG)
    except OSError: pass
    subprocess.run(["sh", up], env=dict(os.environ, **env), timeout=30)
    return open(ZLOG).read() if os.path.exists(ZLOG) else ""
a = ran({})
check("deck-up: web on by default", "--web-sharing on" in a and "web --start" in a)
a = ran({"PHOSPHOR_WEB": "0"})
check("deck-up: PHOSPHOR_WEB=0, no web at all", "--create-background" in a and "web" not in a)
rescue.UP = os.path.join(tmp, "%s-up.sh")
os.rename(up, rescue.UP % SESS)
check("w is offered only by a deck-up that reads PHOSPHOR_WEB", rescue.can_skip_web(SESS)
      and not rescue.can_skip_web("nothing-here"))

# 8. the screen, in a pty
SC = os.path.join(tmp, "systemctl-argv")
UPMARK = os.path.join(tmp, "up")
open(os.path.join(bin_, "systemctl"), "w").write(r'''#!/bin/sh
echo "$@" >> %(log)s
case "$*" in
  *"show "*) printf 'ActiveState=activating\nSubState=start\nResult=success\nExecMainStatus=0\nStateChangeTimestampMonotonic=1\nInactiveExitTimestampMonotonic=1\n' ;;
  *is-active*) echo active ;;
  *"restart "*) touch %(up)s ;;
esac
''' % {"log": SC, "up": UPMARK})
open(os.path.join(bin_, "journalctl"), "w").write("#!/bin/sh\necho a journal line\n")
for f in ("systemctl", "journalctl"):
    os.chmod(os.path.join(bin_, f), 0o755)
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(PATH=bin_ + ":/usr/bin:/bin", TERM="xterm-256color", COLUMNS="60", LINES="30",
           HOME=tmp, PHOSPHOR_DATA=os.path.join(tmp, "data"), PHOSPHOR_CACHE=os.path.join(tmp, "cache"))
# The browser-access server, other screens' `deck`: real ones belong to no
# session in particular, and a 1 or k here would close them. This screen
# sees only the processes this test made (RESCUE_PIDS).
CODE = ("import os, sys; sys.path.insert(0, %r); import rescue; rescue.UP = %r\n"
        "_h = rescue.holders; mine = set(map(int, os.environ['RESCUE_PIDS'].split()))\n"
        "rescue.holders = lambda s, me=None: [h for h in _h(s, me) if h[0] in mine]\n"
        "r = rescue.screen('zellij', %r, {'deck': {'web': True}}, lambda: os.path.exists(%r))\n"
        "print('SCREEN-' + str(r) + '-DONE')" % (os.path.join(ROOT, "lib"), rescue.UP, SESS, UPMARK))

def read(fd, secs, until):
    out, end = b"", time.time() + secs
    while time.time() < end and not until(out):
        if select.select([fd], [], [], 0.05)[0]:
            try: out += os.read(fd, 65536)
            except OSError: break
    return out

def reading_keys(fd, secs):
    end = time.time() + secs
    while time.time() < end:
        try:
            if not termios.tcgetattr(fd)[3] & termios.ICANON: return True
        except termios.error:
            return False
        time.sleep(0.02)
    return False

def session(keys, pids=()):
    """The screen with keys [(what it waits for, key)], seeing only pids:
    (what it printed, how it ended)."""
    ENV["RESCUE_PIDS"] = " ".join(map(str, pids)) or "0"
    for f in (SC, UPMARK):
        try: os.unlink(f)
        except OSError: pass
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, "-c", CODE], ENV)
    seen = b""
    for wait, key in keys:
        seen += read(fd, 20, lambda o: wait in o)
        reading_keys(fd, 5)
        os.write(fd, key)
    seen += read(fd, 40, lambda o: b"-DONE" in o)
    try: os.kill(pid, 9)
    except OSError: pass
    os.waitpid(pid, 0)
    m = re.search(rb"SCREEN-(\w+)-DONE", seen)
    return seen, (m.group(1).decode() if m else None)

held = subprocess.Popen(["bash", "-c", 'exec -a zellij python3 -c "import time; time.sleep(60)" attach --create-background %s' % SESS])
time.sleep(0.3)
seen, how = session([(b"retry the start", b"1"), (b"closed a start that never finished", b"q")], [held.pid])
check("screen: says what holds it up", b"a start that never finished" in seen)
check("screen: 1 closes that one", held.wait(timeout=5) is not None)
check("screen: q leaves, the deck not up", how == "False")
check("screen: q restarted nothing", "restart" not in (open(SC).read() if os.path.exists(SC) else ""))

held = subprocess.Popen(["bash", "-c", 'exec -a zellij python3 -c "import time; time.sleep(60)" attach --create-background %s' % SESS])
time.sleep(0.3)
seen, how = session([(b"retry the start", b"r")], [held.pid])
calls = open(SC).read() if os.path.exists(SC) else ""
check("screen: r closes the hung start", held.wait(timeout=5) is not None)
check("screen: r restarts deck.service and the watchdog",
      "--user restart %s.service" % SESS in calls and "--user start %s.timer" % SESS in calls)
check("screen: r leaves PHOSPHOR_WEB alone", "PHOSPHOR_WEB" not in calls)
check("screen: up, it goes in", how == "True" and b"going in" in seen)

seen, how = session([(b"retry the start", b"w")])
calls = open(SC).read() if os.path.exists(SC) else ""
order = [l for l in calls.splitlines() if "PHOSPHOR_WEB" in l or "restart" in l]
check("screen: w restarts with PHOSPHOR_WEB=0, then unsets it",
      order == ["--user set-environment PHOSPHOR_WEB=0", "--user restart %s.service" % SESS,
                "--user unset-environment PHOSPHOR_WEB"])
check("screen: w, up, it goes in", how == "True")

seen, how = session([(b"retry the start", b"l"), (b"a journal line", b"q"), (b"retry the start", b"q")])
check("screen: l shows deck.service's journal, q back to the screen", b"a journal line" in seen and how == "False")

print("rescue-check: %s" % ("FAIL: " + "; ".join(fails) if fails else "ok"))
sys.exit(1 if fails else 0)
