#!/usr/bin/env python3
"""`/` in the + menu searches everything at once: open tabs, the menu's own
entries, workspaces, installed tools and every command (#46).

    python3 tests/search-check.py

First the pure parts (what's found, in what order) in a throwaway HOME, then
the real thing in a throwaway zellij (tests/zjprobe.py): + -> / -> a name ->
Enter, once to go to an open tab and once to run a command.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

tmp = tempfile.mkdtemp()
env0 = dict(os.environ)
os.environ.update(HOME=tmp, PHOSPHOR_DATA=os.path.join(tmp, "data"),
                  PHOSPHOR_PROFILE=os.path.join(tmp, "none.toml"),
                  PATH=os.path.join(tmp, ".local/bin") + ":/usr/bin:/bin")
for k in [k for k in os.environ if k.startswith("ZELLIJ")]:
    del os.environ[k]
bin_ = os.path.join(tmp, ".local/bin"); os.makedirs(bin_)
open(os.path.join(bin_, "lazygit"), "w").write("#!/bin/sh\n")      # a catalog tool, installed
os.chmod(os.path.join(bin_, "lazygit"), 0o755)
proj = os.path.join(tmp, "projects")
os.makedirs(os.path.join(proj, "rocket")); open(os.path.join(proj, "rocket", "NOTES.md"), "w").close()
os.makedirs(os.path.join(proj, "plain"))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import newtab

prof = {"deck": {"projects": proj}}
its = newtab.entries(prof)
items = newtab.search_items(prof, its)
kinds = {it[2] for it in items}
need("menu entries are searchable", any(it[2] == "entry" and it[0] == "services" for it in items))
need("every command is searchable", any(it[2] == "command" and it[0] == "doctor" for it in items))
need("a workspace is searchable", any(it[2] == "workspace" and it[0] == "rocket" for it in items))
need("a folder without NOTES.md isn't a workspace", not any(it[0] == "plain" for it in items))
need("an installed catalog tool is searchable", any(it[2] == "app" and it[0] == "lazygit" for it in items))
need("a tool that isn't installed isn't", not any(it[2] == "app" and it[0] == "gomuks" for it in items))
need("outside the deck: no open tabs", "tab" not in kinds)

f = newtab.find(items, "services")
need("the exact name first, the menu entry before the command",
     f and f[0][2] == "entry" and any(it[2] == "command" and it[0] == "services" for it in f))
f = newtab.find(items, "DOC")
need("case-insensitive, name before note", f and f[0][0] == "doctor")
f = newtab.find(items, "systemd units")
need("every word, in the note too", f and all("systemd" in (i[0] + i[1]).lower() for i in f))
need("nothing for nonsense", newtab.find(items, "zzqqxx") == [])
need("an empty query lists everything", len(newtab.find(items, "  ")) == len(items))

need("a workspace without a layout says phosphor gen",
     "phosphor gen" in (newtab.open_workspace("rocket") or ""))

# the one-line key hint: the deck's keys as [keys] has them, then it stops
h = newtab.hint({"keys": {"edit": "Ctrl e"}})
need("the hint names the deck's keys, yours included", h and "Ctrl-e edit tab" in h and "Alt-j note" in h)
for _ in range(newtab.HINT_SHOWS): newtab.hint(prof)
need("the hint stops after HINT_SHOWS opens", newtab.hint(prof) is None)

os.environ.clear(); os.environ.update(env0)

# The real flow in a throwaway zellij.
import zjprobe
PROFILE = '''
[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "SH"
panes = [ { cmd = "" } ]

[[tabs]]
name  = "LOGBOOK"
panes = [ { cmd = "" } ]
'''

def active(z):
    import re
    lay = z.action("dump-layout")
    m = re.search(r'^\s*tab name="([^"]*)"[^\n]*focus=true', lay, re.M)
    return m.group(1) if m else None

if not zjprobe.zellij():
    print("no zellij here: the pty part skipped")
else:
    with zjprobe.Probe(PROFILE) as z:
        z.pump(2)
        z.action("go-to-tab-name", "SH"); z.pump(1)
        before = z.tabs()
        def search_for(q):
            """+ -> / -> q, each step once the screen shows it took the last
            one: fixed waits typed into a menu still starting on a busy runner."""
            z.out = b""; z.action("new-tab")
            ok = z.wait(lambda: b"everything" in z.out, 10)
            z.out = b""; z.keys("/", 0.2)
            ok = z.wait(lambda: b"SEARCH" in z.out, 8) and ok
            for ch in q:                  # zellij redraws only what changed: one letter each
                z.out = b""; z.keys(ch, 0.1)
                ok = z.wait(lambda: ch.encode() in z.out, 8) and ok
            return ok
        need("+ opens the menu, / its search", search_for("logbo"))
        need("+ opens the menu in a tab of its own", len(z.tabs()) == len(before) + 1)
        z.keys("\r", 2)
        need("an open tab: Enter goes there", z.wait(lambda: active(z) == "LOGBOOK", 8))
        need("and the menu's tab closes", z.wait(lambda: len(z.tabs()) == len(before), 8))

        need("again, for a command", search_for("keys"))
        z.keys("\r", 3)
        need("a read-only command: Enter runs it in that tab, named after it",
             z.wait(lambda: "KEYS" in z.tabs(), 8))

import shutil
shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("ok")
