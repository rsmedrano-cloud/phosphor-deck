#!/usr/bin/env python3
"""Panels of your own (panels.d): a good one loads and opens in a pty,
listing them never runs a file, a broken file or one with no ListPanel
says why, a fetch / action / confirmed action that raises shows on screen
instead of ending the pane, TITLE draws the top bar, and they show in the
store's "yours" and the + menu.

    python3 tests/panels-check.py
"""
import json, os, pty, select, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
tmp = tempfile.mkdtemp()
d = os.path.join(tmp, "panels.d"); os.makedirs(d)
marker = os.path.join(tmp, "ran")
os.environ.update(HOME=tmp, PHOSPHOR_PANELS=d, PHOSPHOR_APPS=os.path.join(tmp, "apps.toml"),
                  PHOSPHOR_PROFILE=os.path.join(tmp, "none.toml"))

fails = []
def need(what, ok):
    if not ok: fails.append(what)

open(os.path.join(d, "backups.py"), "w").write('''"""restic snapshots on the NAS
more text"""
import tui
open(%r, "a").write("x")
class Backups(tui.ListPanel):
    TITLE = "BACKUPS"
    KEYS = [("enter", "files"), ("x", "boom"), ("c", "ask"), ("q", "quit")]
    def fetch(self):
        return ["snap-a", "snap-b"]
    def lines(self, w, sel):
        return [("> " if i == sel else "  ") + r for i, r in enumerate(self.rows)]
    def act(self, k, row):
        if k == "x": raise ValueError("nope")
        if k == "c": self.confirm("go?", lambda: 1 / 0)
        if k == "enter": self.say("files of " + row)
''' % marker)
open(os.path.join(d, "broken.py"), "w").write('"""breaks"""\nraise RuntimeError("bad import")\n')
open(os.path.join(d, "empty.py"), "w").write('"""no class here"""\nX = 1\n')
open(os.path.join(d, "flaky.py"), "w").write('''import tui
class F(tui.ListPanel):
    def fetch(self): raise OSError("disk gone")
''')
open(os.path.join(d, "_helper.py"), "w").write("raise SystemExit('never')\n")
open(os.path.join(d, "two words.py"), "w").write("")

import panels, apps, newtab
ls = panels.listing()
need("listing: every panel file, by name, no helpers", [p["name"] for p in ls] == ["backups", "broken", "empty", "flaky"])
need("listing: the docstring's first line", ls[0]["desc"] == "restic snapshots on the NAS")
need("listing runs no file", not os.path.exists(marker))

cls, why = panels.load(os.path.join(d, "broken.py"))
need("a file that raises says why", cls is None and "broken.py doesn't load" in why and "bad import" in why)
cls, why = panels.load(os.path.join(d, "empty.py"))
need("a file with no ListPanel says so", cls is None and "needs one class" in why)

cls, why = panels.load(os.path.join(d, "backups.py"))
need("a good panel loads", why is None and cls.__name__ == "Backups")
p = cls(); p.update(); out = p.frame(80, 24)
need("TITLE draws the top bar with the count", "BACKUPS" in out[0] and "2" in out[0])
need("its rows show", any("> snap-a" in l for l in out))
p.key("\r"); need("enter reaches act()", "files of snap-a" in p.msg)
p.key("x"); need("an action that raises is a line, not a crash", "ValueError: nope" in p.msg)
p.key("c"); p.key("y"); need("a confirmed action that raises says so", "ZeroDivisionError" in p.msg)

f, _ = panels.load(os.path.join(d, "flaky.py"))
f = f(); f.update()
need("a fetch that raises is the panel's problem", "disk gone" in f.problem and f.rows == [])

own, _ = apps.yours()
mine = {a["n"]: a for a in own}
need("the store lists them as yours", "backups" in mine and mine["backups"]["c"] == "panel"
     and mine["backups"]["file"].endswith("backups.py"))
need("their spec runs phosphor panels", apps.spec(mine["backups"]) == {"cmd": "phosphor", "args": ["panels", "backups"]})
menu = {e[0]: e for e in newtab.entries({})}
need("the + menu opens them with this checkout's phosphor",
     "backups" in menu and menu["backups"][3] == [os.path.join(ROOT, "phosphor"), "panels", "backups"])

env = dict(os.environ)
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "panels", "--json"],
                   capture_output=True, text=True, env=env)
try:
    j = json.loads(r.stdout)
    need("--json: folder and panels", j["folder"] == d and [p["name"] for p in j["panels"]][0] == "backups")
except ValueError:
    need("--json prints JSON: " + r.stdout[:200] + r.stderr[-300:], False)
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "panels", "nosuch"],
                   capture_output=True, text=True, env=env)
need("an unknown name says so and exits 1", r.returncode == 1 and "no panel nosuch" in r.stdout)
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "panels", "broken"],
                   capture_output=True, text=True, env=env)
need("a broken one says why on the command line", r.returncode == 1 and "bad import" in r.stdout)

# the real thing, in a pty: it draws, and q leaves with exit 0
pid, fd = pty.fork()
if pid == 0:
    os.execvpe(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "panels", "backups"], env)
seen, end = b"", time.time() + 10
while time.time() < end and b"snap-b" not in seen:
    if select.select([fd], [], [], 0.2)[0]:
        try: seen += os.read(fd, 65536)
        except OSError: break
need("in a pty it draws its rows", b"BACKUPS" in seen and b"snap-b" in seen)
time.sleep(0.3)
os.write(fd, b"q")
end = time.time() + 5
while time.time() < end:
    w, status = os.waitpid(pid, os.WNOHANG)
    if w: break
    if select.select([fd], [], [], 0.2)[0]:
        try: os.read(fd, 65536)
        except OSError: pass
else:
    os.kill(pid, 9); os.waitpid(pid, 0); status = -1
need("q leaves it, exit 0", status == 0)

if fails:
    print("FAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok")
