#!/usr/bin/env python3
"""Panels you can act from: `phosphor services` picks a unit and reads its
logs, restarts, starts or stops it (asking first); `phosphor workspace`
lists every workspace with its git state, shows a diff and opens its tab.

    python3 tests/act-check.py

Both run for real, in a pseudo-terminal, against a throwaway HOME, profile,
data and cache and throwaway git repos; systemctl, journalctl, less and
zellij are stand-ins on PATH that only say what they were given. Nothing
of the real deck, and no real unit.
"""
import base64, os, pty, re, select, shutil, signal, subprocess, sys, tempfile, time
import urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(ROOT, "phosphor")

tmp = tempfile.mkdtemp()
BIN = os.path.join(tmp, "bin")
WORK = os.path.join(tmp, "work")
CACHE = os.path.join(tmp, "cache")
for d in (BIN, WORK, CACHE, os.path.join(tmp, ".config", "phosphor")):
    os.makedirs(d, exist_ok=True)
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
open(PROFILE, "w").write('[deck]\nsession = "act-probe"\n\n'
                         '[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n\n'
                         '[services]\ninterval = 30\nextra = ["user:probe.service"]\n')

def stub(name, body):
    p = os.path.join(BIN, name)
    open(p, "w").write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, 0o755)
SCTL = os.path.join(tmp, "systemctl.log")
stub("systemctl", 'echo "$*" >> "%s"\ncase "$*" in *" show "*)\n'
     '  echo LoadState=loaded; echo ActiveState=active; echo SubState=running;; esac' % SCTL)
stub("journalctl", 'echo "LOG-OF $*"')
stub("less", "cat")
ZLOG = os.path.join(tmp, "zellij.log")
os.makedirs(os.path.join(tmp, ".local", "bin"), exist_ok=True)
open(os.path.join(tmp, ".local", "bin", "zellij"), "w").write('#!/bin/sh\necho "$*" >> "%s"\n' % ZLOG)
os.chmod(os.path.join(tmp, ".local", "bin", "zellij"), 0o755)

GIT = shutil.which("git")
ENV = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=CACHE, PHOSPHOR_NOTES="",
           PATH=":".join([BIN] + ([os.path.dirname(GIT)] if GIT else []) + ["/usr/bin", "/bin"]),
           TERM="xterm-256color", LINES="30", COLUMNS="100",
           GIT_AUTHOR_NAME="probe", GIT_AUTHOR_EMAIL="probe@example.org",
           GIT_COMMITTER_NAME="probe", GIT_COMMITTER_EMAIL="probe@example.org")
ENV.pop("PHOSPHOR_NOTES")

fails = []
def need(what, ok, out=""):
    if not ok:
        fails.append(what + ("\n" + out[-600:] if out else ""))


class Term:
    """One command on a pseudo-terminal: keys in, everything it printed out."""
    def __init__(self, *argv, env=None):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(WORK)
            os.execve(sys.executable, [sys.executable, PHOSPHOR] + list(argv), env or ENV)
        self.out = ""

    def read(self, quiet=0.3, limit=10):
        """Until nothing new has come for `quiet` seconds (or it ended)."""
        end = time.time() + limit
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], quiet)
            if not r:
                return self.out
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return self.out
            if not data:
                return self.out
            self.out += data.decode("utf-8", "replace")
        return self.out

    def wait_for(self, text, limit=15):
        end = time.time() + limit
        while text not in self.out and time.time() < end:
            self.read(0.2, 1)
        return text in self.out

    def keys(self, *ks):
        for k in ks:
            self.read()
            os.write(self.fd, k.encode())
        return self

    def done(self, limit=15):
        end = time.time() + limit
        while time.time() < end:
            self.read(0.2, 1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status)
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        return None




def plain(s):
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", s)

def sctl():
    try: return open(SCTL).read()
    except OSError: return ""


# ── services ─────────────────────────────────────────────────
# units in order: act-probe.service, act-probe.timer (the deck's own), probe.service
t = Term("services")
need("services: the panel lists the extra unit", t.wait_for("probe") and t.wait_for("restart"), plain(t.out))
t.keys("j", "j", "l")
need("services: l shows the picked unit's logs", t.wait_for("LOG-OF --user -u probe.service"), plain(t.out))
t.keys("q", "r")
need("services: r asks first", t.wait_for("restart probe?"), plain(t.out))
t.keys("n")
need("services: anything but y leaves it alone", t.wait_for("left alone") and " restart " not in sctl(), sctl())
t.keys("r", "y")
need("services: y restarts it", t.wait_for("restarted probe") and "--user restart probe.service" in sctl(), sctl())
t.keys("s", "y")
need("services: s on a running unit stops it", t.wait_for("stopped probe") and "--user stop probe.service" in sctl(), sctl())
t.keys("k", "k", "r")
need("services: the deck's own service is left to phosphor restart",
     t.wait_for("that's the deck itself") and "act-probe.service" not in sctl().replace("show act-probe", ""), sctl())
t.keys("q")
need("services: q leaves", t.done() == 0, plain(t.out))

t = Term("services", "--once")
need("services --once stays a plain frame", t.done() == 0 and "probe" in plain(t.out) and "restart" not in plain(t.out),
     plain(t.out))

# ── workspace ────────────────────────────────────────────────
PROJ = os.path.join(tmp, "projects")
for n in ("alpha", "beta"):
    d = os.path.join(PROJ, n)
    os.makedirs(d)
    open(os.path.join(d, "NOTES.md"), "w").write("")
    open(os.path.join(d, "plan.txt"), "w").write("first\n")
    if GIT:                                 # the CI image (python:3.12-slim) has none
        subprocess.run("git init -q && git add -A && git commit -qm start", shell=True, cwd=d, env=ENV, check=True)
open(os.path.join(PROJ, "alpha", "plan.txt"), "a").write("CHANGED-LINE\n")

t = Term("workspace")
need("workspace: a panel with every workspace", t.wait_for("WORKSPACES") and t.wait_for("beta"), plain(t.out))
if GIT:
    need("workspace: each one's git state", "dirty" in plain(t.out) and "clean" in plain(t.out), plain(t.out))
    t.keys("d")
    need("workspace: d shows the picked one's diff", t.wait_for("CHANGED-LINE"), plain(t.out))
    t.keys("q")
else:
    need("workspace: without git it says so", "no git" in plain(t.out), plain(t.out))
t.keys("\r")
need("workspace: Enter outside the deck says where it works", t.wait_for("open it from inside the deck"), plain(t.out))
t.keys("n")
need("workspace: n starts a new one", t.wait_for("its name"), plain(t.out))
t.keys("\x03")
need("workspace: backing out of new comes back", t.wait_for("back"), plain(t.out))
t.keys("q", "q")
need("workspace: q leaves", t.done() == 0, plain(t.out))

layouts = os.path.join(tmp, ".config", "zellij", "layouts")
os.makedirs(layouts, exist_ok=True)
open(os.path.join(layouts, "tab-beta.kdl"), "w").write("layout {}\n")
inside = dict(ENV, ZELLIJ="0", ZELLIJ_SESSION_NAME="act-probe")
t = Term("workspace", env=inside).keys("j", "\r")
t.wait_for("BETA")
t.keys("q")
t.done()
zl = open(ZLOG).read() if os.path.exists(ZLOG) else ""
need("workspace: Enter inside the deck opens its tab", "new-tab --layout" in zl and "--name BETA" in zl, zl)

t = Term("workspace", "list")
need("workspace list stays a plain listing", t.done() == 0 and "alpha" in plain(t.out) and "WORKSPACES" not in t.out,
     plain(t.out))

shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print("act-check: FAIL")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("act-check: ok (services and workspace panels)")
