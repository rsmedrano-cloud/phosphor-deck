#!/usr/bin/env python3
"""phosphor glance: read-only, narrow-friendly, no crash on empty state.

    python3 tests/glance-check.py
"""
import json, os, re, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def need(what, ok):
    if not ok: fails.append(what)

def strip(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.makedirs(os.path.join(home, ".cache/phosphor"))
os.makedirs(os.path.join(home, ".local/share/phosphor"))

import glance

# empty state: no fleet cache, no mentions, no notes -- must not crash
lines = [strip(l) for l in glance.frame(40, 40)]
need("empty fleet says so", any("no fleet data" in l for l in lines))
need("empty mentions says so", any("nothing unread" in l for l in lines))
need("empty todos says so", any("nothing pending" in l for l in lines))
need("no workspaces yet says so", any("nothing dirty or unpushed" in l for l in lines))

json.dump({"t": 9999999999, "hosts": {
    "nova": {"ok": True, "CPU": 10, "MEMU": 100, "MEMT": 1000, "mnt": []},
    "forge": {"ok": False, "err": "connection refused"},
    "atlas": {"ok": True, "CPU": 5, "MEMU": 50, "MEMT": 1000, "mnt": [], "SVCFAIL": 2, "REBOOT": "1"},
}}, open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
open(os.path.join(home, ".local/share/phosphor/mentions.jsonl"), "w").write(
    json.dumps({"t": 1.0, "from": "sam", "message": "one comment on the tts PR"}) + "\n")
open(os.path.join(home, ".local/share/phosphor/notes.md"), "w").write(
    "# Notes\n\n## 2026-09-18 20:00 · todo · nova · Check the tailnet ACLs\nbody\n")

lines = [strip(l) for l in glance.frame(80, 40)]
need("bad host shows up", any("forge" in l and "connection refused" in l for l in lines))
need("ok host doesn't clutter the list", not any(l.strip().startswith("✗ nova") for l in lines))
need("a failed service shows up even though the host itself is ok",
     any("atlas" in l and "2 services failed" in l for l in lines))
need("a pending reboot shows up too", any("atlas" in l and "reboot pending" in l for l in lines))
need("unread mention shows up", any("1 unread" in l for l in lines))
need("mention sender/text shows up", any("sam" in l for l in lines))
need("todo shows up", any("1 open todo" in l for l in lines) and any("tailnet" in l for l in lines))

# a dirty workspace (#36): "one device, then another" makes it easy to
# forget which machine has uncommitted changes.
if shutil.which("git"):
    ws = os.path.join(home, "projects", "shop")
    os.makedirs(ws)
    open(os.path.join(ws, "NOTES.md"), "w").write("# shop notes\n")
    subprocess.run(["git", "init", "-q", ws])
    open(os.path.join(ws, "x.txt"), "w").write("wip\n")
    lines = [strip(l) for l in glance.frame(80, 40)]
    need("a dirty workspace shows up", any("shop" in l and "uncommitted" in l for l in lines))

# narrow: must not blow up or produce lines with stray raw escape fragments
narrow = glance.frame(20, 40)
need("narrow width doesn't crash", isinstance(narrow, list) and len(narrow) > 0)

# --once via the real dispatcher: no crash, exits 0
env = dict(os.environ)
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "glance", "--once"],
                   capture_output=True, text=True, env=env, timeout=10)
need("phosphor glance --once exits 0", r.returncode == 0)
need("phosphor glance --once prints something", "GLANCE" in r.stdout)

# --json / --serve (#50): the same answers for a gadget that can't ssh
p = glance.payload()
need("a host down makes the light red", p["status"] == "red")
need("worst is the host that's down, not a pending reboot",
     p["worst"] == {"host": "forge", "detail": "connection refused"})
need("counts come along", p["mentions"] == 1 and p["todos"] == 1 and p["fleet"]["total"] == 3)
json.dump({"t": 9999999999, "hosts": {"nova": {"ok": True, "mnt": [], "REBOOT": "1"}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
need("something to look at, nothing down: amber", glance.payload()["status"] == "amber")
json.dump({"t": 9999999999, "hosts": {"nova": {"ok": True, "mnt": []}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
open(os.path.join(home, ".local/share/phosphor/mentions.jsonl"), "w").write("")
need("all fine: green, todos don't color it", glance.payload()["status"] == "green")
json.dump({"t": 1, "hosts": {"nova": {"ok": True, "mnt": []}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
need("stale readings: red", glance.payload()["status"] == "red")
os.remove(os.path.join(home, ".cache/phosphor/fleet.json"))
need("no fleet data: unknown", glance.payload()["status"] == "unknown")

t1 = glance.token()
need("the token is kept 0600", os.stat(glance.token_path()).st_mode & 0o777 == 0o600)
need("the token survives a restart", glance.token() == t1)
need("--new-token replaces it", glance.token(new=True) != t1)
secret = glance.token()

import socket, threading, time, urllib.request, urllib.error
httpd = glance.server(("127.0.0.1", 0), secret)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % httpd.server_port
def get(path, headers={}):
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
need("no token: 401", get("/glance")[0] == 401)
need("a wrong token: 401", get("/glance?token=nope")[0] == 401)
code, body = get("/glance?token=" + secret)
need("?token= answers the payload", code == 200 and json.loads(body)["status"] == "unknown")
need("Authorization: Bearer works too",
     get("/glance.json", {"Authorization": "Bearer " + secret})[0] == 200)
need("anything else: 404", get("/etc/passwd?token=" + secret)[0] == 404)
stall = socket.create_connection(("127.0.0.1", httpd.server_port))
stall.sendall(b"GET /gla")                 # and never finishes the line
t0 = time.time()
need("a client that stalls doesn't hold the others up",
     get("/glance?token=" + secret)[0] == 200 and time.time() - t0 < 2)
stall.close()
httpd.shutdown()

r = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "glance.py"), "--json"],
                   capture_output=True, text=True, env=dict(os.environ, HOME=home), timeout=20)
need("phosphor glance --json prints JSON", r.returncode == 0 and json.loads(r.stdout).get("status"))

# a wide, short screen (a 130x17 e-ink panel): all four sections in a 2x2
# grid, nothing past the edges, the light in words on top.
json.dump({"t": 9999999999, "hosts": {"forge": {"ok": False, "err": "connection refused"}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
lines = glance.frame(130, 17)
need("130x17: no more than 17 rows", len(lines) <= 17)
need("130x17: no line wider than 130", all(glance.ui.vlen(l) <= 130 for l in lines))
plain = [strip(l) for l in lines]
need("130x17: all four sections show",
     all(any(t in l for l in plain) for t in ("fleet", "mentions", "needs you", "workspaces")))
need("130x17: the light reads in words", "ATTENTION" in plain[0])
need("a todo with no title takes one line, not its whole body",
     all(glance.ui.vlen(l) <= 40 for l in glance.frame(40, 40) if "tailnet" in strip(l)))

# mono: a terminal with no color gets no 24-bit color at all (SolarOS's ssh
# reads the numbers in one as more SGR codes), red and amber become bold.
need("TERM=xterm-mono is mono", glance.ui.mono_term({"TERM": "xterm-mono"}))
need("NO_COLOR is mono", glance.ui.mono_term({"TERM": "xterm-256color", "NO_COLOR": "1"}))
need("xterm-256color is not", not glance.ui.mono_term({"TERM": "xterm-256color"}))
m = [glance.mono(l) for l in lines]
need("mono drops every 24-bit color", not any("38;2;" in l for l in m))
need("mono keeps the red light reversed", "\x1b[7m" in m[0])
need("mono keeps the text", [strip(l) for l in m] == plain)

# the screen that stays up repaints only on a change: one paint while nothing
# moves, a clean repaint on r, out on q. Polling every 0.2 s instead of 5.
import pty, select, time
pid, fd = pty.fork()
if pid == 0:
    os.execve(sys.executable, [sys.executable, "-c",
        "import sys; sys.path.insert(0, %r); import glance; glance.INTERVAL = 0.2;"
        " sys.argv = ['glance']; sys.exit(glance.main())" % os.path.join(ROOT, "lib")],
        dict(os.environ, HOME=home, TERM="xterm-mono", COLUMNS="130", LINES="17"))
seen = ""
def drain(secs):
    global seen
    end = time.time() + secs
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            try: data = os.read(fd, 65536)
            except OSError: return
            if not data: return
            seen += data.decode("utf-8", "replace")
drain(2.5)
need("watch: painted once while nothing changed", seen.count("\x1b[H") == 1)
need("watch: no color on xterm-mono", "38;2;" not in seen and "ATTENTION" in seen)
os.write(fd, b"r"); drain(1.5)
need("watch: r clears and repaints", seen.count("\x1b[2J") == 2 and seen.count("\x1b[H") == 2)
end, code = time.time() + 5, None
while time.time() < end and code is None:
    try: os.write(fd, b"q")             # again if it landed between two reads (setraw flushes it)
    except OSError: pass
    drain(0.5)
    p_, st = os.waitpid(pid, os.WNOHANG)
    if p_: code = os.waitstatus_to_exitcode(st)
if code is None:
    os.kill(pid, 9); os.waitpid(pid, 0)
need("watch: q leaves cleanly", code == 0)

if fails:
    print("FAIL:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
