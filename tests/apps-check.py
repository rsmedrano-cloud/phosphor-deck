#!/usr/bin/env python3
"""Your own apps and the store's installed view.

    python3 tests/apps-check.py

apps.toml parses (and says which entry is broken), your apps come first in
the store and show in the + menu, an installed app opens in a tab with its
flags, and the store's i key narrows to what's installed.
"""
import os, sys, tempfile, pty, select, time, struct, fcntl, termios
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
tool = os.path.join(tmp, "mytool")
open(tool, "w").write("#!/bin/sh\nsleep 1\n"); os.chmod(tool, 0o755)
conf = os.path.join(tmp, "apps.toml")
open(conf, "w").write('''
[[apps]]
name = "My Tool"
cmd  = "%s"
args = ["-x", "1"]
alt  = true

[[apps]]
name = "ghost"
cmd  = "no-such-program-here"

[[apps]]
cmd = "nameless"
''' % tool)
os.environ["PHOSPHOR_APPS"] = conf
os.environ["PHOSPHOR_PROFILE"] = os.path.join(tmp, "none.toml")

import apps, newtab, gen
own, problem = apps.yours()
check("two good entries", [a["n"] for a in own] == ["My Tool", "ghost"])
check("the broken entry is named", problem and "entry 3" in problem)
check("spec keeps the flags", apps.spec(own[0]) == {"cmd": tool, "args": ["-x", "1"], "alt": True})
check("tab name", apps.tab_name(own[0]) == "MYTOOL")

menu = {e[0]: e for e in newtab.entries({})}
check("+ lists an installed app of yours", "My Tool" in menu and menu["My Tool"][3] == [tool, "-x", "1"])
check("+ skips one that isn't installed", "ghost" not in menu)

calls = []
newtab.zj = lambda *a: calls.append(a) or ""
os.environ.pop("ZELLIJ", None)
check("outside the deck it says so", apps.open_tab(own[0]) == (False, "open it from inside the deck"))
os.environ["ZELLIJ"] = "0"
os.environ["HOME"] = tmp                    # the layout lands in a throwaway cache
apps_cache = os.path.join(tmp, ".cache/phosphor/apps")
import importlib; importlib.reload(apps)
apps.newtab = newtab
ok, msg = apps.open_tab(own[0])
news = [c for c in calls if c[0] == "new-tab"]
check("open_tab opens a tab", ok and len(news) == 1 and news[0][-1] == "MYTOOL")
if news:
    lay = open(news[0][2]).read()
    check("the tab runs it with --alt", '"--alt" "--" "%s" "-x" "1"' % tool in lay)
check("a missing one isn't opened", apps.open_tab(own[1])[0] is False)

# the store itself, in a pty: yours first, i narrows to installed
env = dict(os.environ); env.pop("ZELLIJ", None)
pid, fd = pty.fork()
if pid == 0:
    os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "store"], env)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
def screen(send=None, wait=1.5):
    if send: os.write(fd, send)
    out, end = b"", time.time() + wait
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            try: out += os.read(fd, 65536)
            except OSError: break
    return out.decode("utf-8", "replace")
first = screen()
check("store: yours come first", first.find("YOURS") != -1 and first.find("YOURS") < first.find("CHAT"))
narrowed = screen(b"i")
check("store: i shows installed only", "· installed" in narrowed and "ghost" not in narrowed)
opened = screen(b"\r")
check("store: Enter on installed opens (asks for the deck here)", "open it from inside the deck" in opened)
os.write(fd, b"q")
try: os.waitpid(pid, 0)
except ChildProcessError: pass

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
