#!/usr/bin/env python3
"""`phosphor restart` only starts a new deck once the old one is proven gone:
the session no longer listed by zellij, its service no longer active, no
process of it left after SIGKILL. Otherwise it stops there, starts nothing,
and exits non-zero -- so an unattended `phosphor update` fails loudly
instead of leaving new code on disk next to old panes.

    python3 tests/down-gate-check.py

No real zellij or systemd: a fake of each in a scratch HOME/PATH, logging
what they were asked. A real process carrying the session's mark proves
the reaper still runs before the verdict.
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import reap

fails = []
def check(what, ok, out=""):
    if not ok:
        fails.append(what + ("\n      " + out.strip().replace("\n", "\n      ") if out else ""))

# 1. the verdict itself
check("a clean slate has no problems", reap.down_problems(True, "inactive", []) == [])
check("a failed unit isn't the old deck running", reap.down_problems(True, "failed", []) == [])
check("an unknown unit (no systemd) doesn't block", reap.down_problems(True, "", []) == [])
p = reap.down_problems(False, "deactivating", [(42, "phosphor fleet")], "probe")
check("each problem is named", len(p) == 3 and "probe" in p[0] and "deactivating" in p[1] and "pid 42" in p[2], "\n".join(p))

# 2. the real command, against fakes
SESS = "gate-probe-%d" % os.getpid()
ZJ = r'''#!/bin/sh
st="$HOME/zj-state"; echo "zellij $*" >> "$HOME/calls"
case "$1" in
  list-sessions) [ -f "$st" ] && echo "%(s)s" ;;
  kill-session)  [ -f "$HOME/zj-sticky" ] || rm -f "$st" ;;
  delete-session) : ;;
  -s) echo "    tab name=\"SYS\"" ;;
esac
''' % {"s": SESS}
SYSTEMCTL = r'''#!/bin/sh
echo "systemctl $*" >> "$HOME/calls"
case "$*" in
  *is-active*timer*) echo active ;;
  *is-active*) cat "$HOME/svc-state" 2>/dev/null || echo inactive ;;
  *"start %(s)s.service"*) touch "$HOME/zj-state" ;;
esac
''' % {"s": SESS}

def run(case):
    home = tempfile.mkdtemp(prefix="down-gate-")
    try:
        bind = os.path.join(home, ".local", "bin"); os.makedirs(bind)
        for name, body in (("zellij", ZJ), ("systemctl", SYSTEMCTL)):
            f = os.path.join(bind, name)
            open(f, "w").write(body); os.chmod(f, 0o755)
        prof = os.path.join(home, "deck.toml")
        open(prof, "w").write('[deck]\nsession = "%s"\n' % SESS)
        open(os.path.join(home, "zj-state"), "w").close()        # the old deck is up
        if case == "busy":
            open(os.path.join(home, "svc-state"), "w").write("deactivating\n")
        if case == "sticky":
            open(os.path.join(home, "zj-sticky"), "w").close()
        env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
        env.update(HOME=home, PATH=bind + os.pathsep + env.get("PATH", ""), PHOSPHOR_PROFILE=prof,
                   NO_COLOR="1")
        # a pane of the old deck: reaped before the verdict, whatever the case
        pane = subprocess.Popen(["sleep", "60"], env=dict(env, ZELLIJ_SESSION_NAME=SESS))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "restart"], env=env,
                           capture_output=True, text=True, timeout=120)
        reaped = pane.poll() is not None
        if not reaped: pane.kill()
        pane.wait()
        try: calls = open(os.path.join(home, "calls")).read()
        except OSError: calls = ""
        started = ("start %s.service" % SESS) in calls
        marker = os.path.exists(os.path.join(home, ".cache", "phosphor", "restarting"))
        return r.returncode, r.stdout + r.stderr, started, reaped, marker
    finally:
        shutil.rmtree(home, ignore_errors=True)

rc, out, started, reaped, marker = run("clean")
check("clean: the old pane is reaped", reaped, out)
check("clean: the new deck starts", started, out)
check("clean: exit 0", rc == 0, out)

for case, why in (("busy", "is still deactivating"), ("sticky", "still lists the session")):
    rc, out, started, reaped, marker = run(case)
    check("%s: the old pane is still reaped" % case, reaped, out)
    check("%s: no new deck is started" % case, not started, out)
    check("%s: exits non-zero" % case, rc != 0, out)
    check("%s: says why" % case, why in out, out)
    check("%s: screens aren't left waiting on a restart that won't come" % case, not marker, out)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
