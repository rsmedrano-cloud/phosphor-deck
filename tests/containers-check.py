#!/usr/bin/env python3
"""phosphor containers: listing parses and sorts, states classify, a name
that came from the host never reaches a shell line unless it looks like a
container's, escape sequences in names and logs are dropped, and the whole
local path (list, logs, restart) works against a fake docker on PATH.
FLEET's `c` opens it in a tab.

    python3 tests/containers-check.py
"""
import os, stat, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import containers as C
from ui import PH, RED, DIM, AMB

fails = []
def need(what, ok):
    if not ok: fails.append(what)

# ── parsing ───────────────────────────────────────────────────
out = ("ENGINE=docker\n"
       "web\trunning\tUp 3 days\tnginx:1\n"
       "evil\x1b]52;c;aGk=\x07\texited\tExited (1) 2 hours ago\talpine\n")
e, rows, err = C.parse(out)
need("engine read", e == "docker")
need("two rows", len(rows) == 2)
need("OSC 52 stripped from a name", rows[1][0] == "evil")
need("no ENGINE line: no engine", C.parse("ENGINE=\n")[0] == "")

# ── classifying ───────────────────────────────────────────────
need("running is green", C.classify("running", "Up 3 days") == (PH, "running"))
need("exit 0 is quiet", C.classify("exited", "Exited (0) 1 hour ago") == (DIM, "exited"))
need("exit 137 is loud", C.classify("exited", "Exited (137) 5 minutes ago") == (RED, "exit 137"))
need("restarting is amber", C.classify("restarting", "Restarting (1)")[0] == AMB)
need("since() drops the verb", C.since("Exited (1) 40 minutes ago") == "40 minutes ago")

# ── commands: a host's name never reaches a shell unchecked ──
need("restart command", C.command("docker", "restart", "web") == "docker restart web")
need("podman too", C.command("podman", "stop", "a.b_c-1") == "podman stop a.b_c-1")
for bad in ("web; rm -rf ~", "$(id)", "-rf", "", "a b", "../x"):
    need("rejects %r" % bad, C.command("docker", "restart", bad) is None)
need("unknown engine rejected", C.command("sh", "restart", "web") is None)
need("unknown verb rejected", C.command("docker", "rm", "web") is None)

# ── lines render at phone width ──────────────────────────────
from ui import vlen
for l in C.lines(rows, 30, sel=0) + C.lines(rows, 30):
    need("line fits 30 cols: %r" % l, vlen(l) <= 30)

# ── hosts ─────────────────────────────────────────────────────
prof = {"hosts": [{"name": "brainbox", "role": "brain", "local": True},
                  {"name": "db-box", "role": "node", "ssh": "db-box", "user": "ops"}]}
need("no host: this machine", C.find(prof, None) == ("brainbox", None))
need("remote host target", C.find(prof, "db-box") == ("db-box", "ops@db-box"))
need("unknown host", C.find(prof, "nimbus") is None)

# ── demo ──────────────────────────────────────────────────────
e, rows, problem = C.fetch("relay", None, demo=True)
need("demo relay is podman", e == "podman" and not problem)
need("demo has a failed one", any(C.classify(r[1], r[2])[0] == RED for r in rows))

# ── the local path, against a fake docker ─────────────────────
d = tempfile.mkdtemp()
log = os.path.join(d, "calls")
fake = os.path.join(d, "docker")
with open(fake, "w") as f:
    f.write("""#!/bin/sh
echo "$*" >> %s
case "$1" in
  ps) case "$*" in *--format*) printf 'zeta\\texited\\tExited (2) 1 minute ago\\tx\\nalpha\\trunning\\tUp 1 hour\\ty\\n';; esac;;
  logs) printf 'hello\\n\\033]0;pwned\\007world\\n';;
  restart|start|stop) exit 0;;
esac
""" % log)
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
e, rows, problem = C.fetch("brainbox", None)
need("fake docker found: %r" % problem, e == "docker" and not problem)
need("running sorted first", [r[0] for r in rows] == ["alpha", "zeta"])
text = C.logs(None, "docker", "alpha")
need("logs read", "hello" in text and "world" in text)
need("title escape dropped from logs", "\x1b]0" not in text)
ok, m = C.act(None, "docker", "restart", "alpha")
need("restart ok: %s" % m, ok and m == "restarted alpha")
calls = open(log).read()
need("restart reached docker", "restart alpha" in calls)
ok, m = C.act(None, "docker", "restart", "x; touch %s/pwned" % d)
need("bad name refused", not ok and not os.path.exists(os.path.join(d, "pwned")))

# ── FLEET's c ─────────────────────────────────────────────────
import fleet
need("c is a FLEET action", "c" in [k for k, _ in fleet.ACTIONS])
label, spec = fleet.action_tab("c", "db-box", "ops@db-box")
need("c opens phosphor containers HOST", label == "CTR-DB-BOX"
     and spec == {"cmd": "phosphor containers", "args": ["db-box"]})

if fails:
    print("containers-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("containers-check ok")
