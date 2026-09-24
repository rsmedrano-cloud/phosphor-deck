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
}}, open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
open(os.path.join(home, ".local/share/phosphor/mentions.jsonl"), "w").write(
    json.dumps({"t": 1.0, "from": "sam", "message": "one comment on the tts PR"}) + "\n")
open(os.path.join(home, ".local/share/phosphor/notes.md"), "w").write(
    "# Notes\n\n## 2026-09-18 20:00 · todo · nova · Check the tailnet ACLs\nbody\n")

lines = [strip(l) for l in glance.frame(80, 40)]
need("bad host shows up", any("forge" in l and "connection refused" in l for l in lines))
need("ok host doesn't clutter the list", not any(l.strip().startswith("✗ nova") for l in lines))
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

if fails:
    print("FAIL:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
