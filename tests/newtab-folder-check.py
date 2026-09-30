#!/usr/bin/env python3
"""An assistant from the + menu asks which folder it starts in: here, a
folder of [deck] projects (workspaces say so), one typed before, or any
other one typed now.

    python3 tests/newtab-folder-check.py

Only the pure parts (places, resolve, remember); a throwaway HOME and data
folder, nothing of the real ones.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.environ["PHOSPHOR_DATA"] = os.path.join(tmp, "data")
os.environ["PHOSPHOR_PROFILE"] = os.path.join(tmp, "none.toml")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import newtab

fails = []
def need(what, ok):
    if not ok: fails.append(what)

proj = os.path.join(tmp, "code")
for d in ("alpha", "beta", ".hidden"):
    os.makedirs(os.path.join(proj, d))
open(os.path.join(proj, "beta", "NOTES.md"), "w").close()
other = os.path.join(tmp, "elsewhere", "thing")
os.makedirs(other)
prof = {"deck": {"projects": proj}}
here = os.path.join(tmp, "elsewhere")

# services always in the + menu; review only with glab or gh, and it asks for a
# repo unless the pane's folder already is one with a GitLab or GitHub remote
import time as _time
labels = [e[0] for e in newtab.entries(prof)]
need("services is in the + menu", "services" in labels)
real_exe = newtab.deckconf.exe
newtab.deckconf.exe = lambda name: None
need("no glab/gh: no review in the + menu", "review" not in [e[0] for e in newtab.entries(prof)])
newtab.deckconf.exe = lambda name: "/usr/bin/gh" if name == "gh" else None
need("gh installed: review in the + menu", "review" in [e[0] for e in newtab.entries(prof)])
newtab.deckconf.exe = real_exe
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
import review   # the check image has no git: a GitLab remote is "being in repo"
real_provider = review.provider
review.provider = lambda url=None: "gitlab" if os.getcwd() == repo else None
cwd0 = os.getcwd()
os.chdir(repo)
need("review in a GitLab repo: no folder question", newtab.review_folder(prof, 20) == repo)
os.chdir(here)
picks = [os.path.join(proj, "alpha"), repo]
real_where, real_sleep = newtab.where, _time.sleep
newtab.where = lambda label, prof, rows: picks.pop(0) if picks else None
newtab.time.sleep = lambda s: None
real_out = sys.stdout; sys.stdout = open(os.devnull, "w")
try:
    got = newtab.review_folder(prof, 20)
finally:
    sys.stdout = real_out; newtab.where = real_where; newtab.time.sleep = real_sleep
need("review outside a repo: a folder without a remote is refused, the repo taken",
     got == repo and not picks and os.getcwd() == here)
os.chdir(cwd0)
review.provider = real_provider

ps = newtab.places(here, prof)
need("here comes first", ps[0][0] == "here" and ps[0][2] == here)
labels = [p[0] for p in ps]
need("projects' folders listed", "alpha" in labels and "beta" in labels)
need("hidden folders left out", ".hidden" not in labels)
need("a workspace says so", any(p[0] == "beta" and p[1].startswith("workspace") for p in ps))
need("a plain folder doesn't", any(p[0] == "alpha" and not p[1].startswith("workspace") for p in ps))
need("paths shown with ~", ps[1][1].endswith("~/code/alpha"))

need("relative path resolves", newtab.resolve("thing", here) == other)
need("~ path resolves", newtab.resolve("~/elsewhere/thing", "/") == other)
need("a file isn't a folder", newtab.resolve("~/code/beta/NOTES.md", "/") is None)
need("missing folder is None", newtab.resolve("nope", here) is None)
need("empty is None", newtab.resolve("  ", here) is None)

newtab.remember(other)
newtab.remember(os.path.join(proj, "alpha"))
newtab.remember(other)
need("remembered with ~, newest first, no duplicates",
     newtab.recent() == ["~/elsewhere/thing", "~/code/alpha"])
ps = newtab.places(proj, prof)
need("a typed folder comes back", ps[-1][2] == other)
need("no path twice", len({p[2] for p in ps}) == len(ps))
for i in range(12):
    d = os.path.join(tmp, "many", str(i)); os.makedirs(d); newtab.remember(d)
need("recent list capped", len(newtab.recent()) == newtab.RECENT)
os.rmdir(os.path.join(tmp, "many", "11"))
need("a folder that's gone drops out", "~/many/11" not in newtab.recent())

need("no projects folder is fine", newtab.places(here, {"deck": {"projects": "/nonexistent"}})[0][0] == "here")

# The real flow in a pty: + menu -> the assistant -> "/" -> a typed folder.
# A fake `claude` writes where it started; nothing real runs.
import pty, select, time
bin_ = os.path.join(tmp, "bin"); os.makedirs(bin_)
out = os.path.join(tmp, "started-in")
open(os.path.join(bin_, "claude"), "w").write("#!/bin/sh\npwd > %s\n" % out)
os.chmod(os.path.join(bin_, "claude"), 0o755)
open(os.path.join(tmp, ".profile"), "w").write('PATH="%s:$PATH"\n' % bin_)   # the pane runs bash -l
env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
env.update(PATH=bin_ + ":" + env.get("PATH", ""), TERM="xterm", COLUMNS="80", LINES="24")
pid, fd = pty.fork()
if pid == 0:
    os.chdir(here)
    os.execvpe(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "new"], env)
def feed(keys, wait=0.8):
    end = time.time() + wait
    while time.time() < end:
        if select.select([fd], [], [], 0.05)[0]:
            try: os.read(fd, 65536)
            except OSError: return
    if keys: os.write(fd, keys.encode())
labels = [l.split()[0] for l in __import__("subprocess").run(
    [sys.executable, os.path.join(ROOT, "phosphor"), "new"], env=dict(env, PHOSPHOR_DATA=env["PHOSPHOR_DATA"]),
    capture_output=True, text=True, stdin=__import__("subprocess").DEVNULL, cwd=here).stdout.splitlines()]
n = labels.index("Claude") + 1 if "Claude" in labels else 0
need("the fake claude shows in the menu", n > 0)
if n:
    feed(str(n)); feed("/"); feed("~/code/alpha\n", 1.0); feed("", 3.0)
    need("claude started in the typed folder",
         os.path.exists(out) and open(out).read().strip() == os.path.join(proj, "alpha"))
try: os.kill(pid, 9)
except OSError: pass

if fails:
    print("FAIL: " + "; ".join(fails)); sys.exit(1)
print("ok")
