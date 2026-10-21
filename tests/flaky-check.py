#!/usr/bin/env python3
"""The quarantine runs a listed test twice, and only a listed one.

    python3 tests/flaky-check.py

tests/flaky.py against a list of its own and a throwaway cache: a listed
test that fails once passes, says FLAKY and is counted; one that fails
twice fails; a test not on the list fails on its first run, with no second.
And every name in tests/flaky.json is a test that exists.
"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(dir=os.path.join(ROOT, "tests"), prefix=".flaky-check-")
fails = []
try:
    def script(name, fail_runs):
        """A test that fails its first fail_runs runs, then passes; it counts in a file."""
        p = os.path.join(tmp, name)
        open(p, "w").write("import os, sys\nf = %r\nn = int(open(f).read()) if os.path.exists(f) else 0\n"
                           "open(f, 'w').write(str(n + 1))\nsys.exit(1 if n < %d else 0)\n"
                           % (p + ".runs", fail_runs))
        return p
    rel = lambda p: os.path.relpath(p, ROOT)
    once, twice, unlisted = script("once.py", 1), script("twice.py", 2), script("unlisted.py", 1)
    lst = os.path.join(tmp, "list.json")
    json.dump({rel(once): "fails once", rel(twice): "fails twice"}, open(lst, "w"))
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    env.update(FLAKY_LIST=lst, XDG_CACHE_HOME=tmp)

    def run(p):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "flaky.py"), sys.executable, rel(p)],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        return r.returncode, r.stdout, int(open(p + ".runs").read())

    rc, out, runs = run(once)
    if rc != 0 or runs != 2 or "FLAKY %s:" % rel(once) not in out:
        fails.append("a listed test that fails once: rc %d after %d runs, said %r" % (rc, runs, out[-200:]))
    saved = json.load(open(os.path.join(tmp, "phosphor", "flakes.json"))).get(rel(once), {}).get("saved")
    if saved != 1:
        fails.append("a listed test saved by its second run wasn't counted (%r)" % saved)
    rc, out, runs = run(twice)
    if rc == 0 or runs != 2 or "FLAKY" in out:
        fails.append("a listed test that fails twice: rc %d after %d runs" % (rc, runs))
    rc, out, runs = run(unlisted)
    if rc == 0 or runs != 1:
        fails.append("a test not on the list: rc %d after %d runs (one run, then fail)" % (rc, runs))
finally:
    subprocess.run(["rm", "-rf", tmp])

for t in json.load(open(os.path.join(ROOT, "tests", "flaky.json"))):
    if not os.path.isfile(os.path.join(ROOT, t)):
        fails.append("tests/flaky.json lists %s, which isn't there" % t)
if fails:
    print("\n".join(fails)); sys.exit(1)
