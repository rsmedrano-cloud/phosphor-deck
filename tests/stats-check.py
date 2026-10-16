#!/usr/bin/env python3
"""phosphor stats: every phosphor CMD counts one run of CMD (name only,
never its arguments), split by how it started; --help, unknown commands
and hidden plumbing count nothing; a broken stats.json never breaks a
command; parallel runs don't lose counts.

    python3 tests/stats-check.py

A throwaway PHOSPHOR_CACHE; the commands run here only read.
"""
import json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def need(what, ok):
    if not ok: fails.append(what)

cache = tempfile.mkdtemp()
home = tempfile.mkdtemp()
env = dict(os.environ, PHOSPHOR_CACHE=cache, HOME=home)
env.pop("PHOSPHOR_RUN", None)
FILE = os.path.join(cache, "stats.json")

def run(*a, **kw):
    return subprocess.run([sys.executable, os.path.join(ROOT, "phosphor")] + list(a), env=kw.get("env", env),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

def counts():
    try:
        return json.load(open(FILE))["commands"]
    except (OSError, ValueError, KeyError):
        return {}

run("version")
run("path", "/secret/place")
run("note", "--help")
run("nosuch-command")
run("help")
run("--version")
c = counts()
need("version counted twice (-V/--version is version): %r" % c.get("version"), (c.get("version") or {}).get("script") == 2)
need("path counted", (c.get("path") or {}).get("script") == 1)
need("help counted", (c.get("help") or {}).get("script") == 1)
need("--help counts nothing: %r" % c.get("note"), "note" not in c)
need("an unknown command counts nothing", "nosuch-command" not in c)
need("arguments never land in the file", "secret" not in open(FILE).read())
need("each has its last day", all(v.get("last") for v in c.values()))

# a tab's pane: PHOSPHOR_RUN names the parent as the run that started it
p = subprocess.run(["sh", "-c", 'PHOSPHOR_RUN="$$ FLEET" "$0" "$1" version; true', sys.executable,
                    os.path.join(ROOT, "phosphor")], env=env, stdin=subprocess.DEVNULL, capture_output=True)
need("a pane started by phosphor run counts as pane: %r" % counts().get("version"),
     (counts().get("version") or {}).get("pane") == 1)

# plumbing isn't counted
run("mention-hook")
need("hidden commands aren't counted", "mention-hook" not in counts())

# many at once, as on a restart: none lost
before = (counts().get("version") or {}).get("script", 0)
with ThreadPoolExecutor(12) as ex:
    list(ex.map(lambda _: run("version"), range(24)))
need("24 parallel runs, 24 counts: %r" % counts().get("version"),
     (counts().get("version") or {}).get("script", 0) == before + 24)

# the summary
r = run("stats", "--json")
s = json.loads(r.stdout)
need("--json has since/commands/never", set(s) == {"since", "commands", "never"})
top = s["commands"][0]
need("most run first: %r" % top, top["name"] == "version" and top["runs"] == top["terminal"] + top["pane"] + top["script"])
need("never lists a command not run", "doctor" in s["never"] and "version" not in s["never"])
need("never leaves hidden ones out", "run" not in s["never"])
r = run("stats")
need("the panel prints a table: %r" % r.stdout[:200], r.returncode == 0 and "version" in r.stdout and "never run" in r.stdout)

# a broken file: the command still runs, counting starts again
open(FILE, "w").write("{not json")
r = run("version")
need("a broken stats.json doesn't break the command", r.returncode == 0)
need("and counting starts again", (counts().get("version") or {}).get("script") == 1)

# a cache that can't be written: still runs
ro = dict(env, PHOSPHOR_CACHE="/proc/no-such/cache")
r = run("version", env=ro)
need("an unwritable cache doesn't break the command: %r" % r.stderr[-200:], r.returncode == 0 and not r.stderr.strip())

r = run("stats", "--clear")
need("--clear empties it", r.returncode == 0 and not counts())

if fails:
    print("\n".join("FAIL: " + f for f in fails)); sys.exit(1)
print("ok: stats")
