#!/usr/bin/env python3
"""The quarantine runs a listed test twice, and only a listed one.

    python3 tests/flaky-check.py

tests/flaky.py against a list of its own and a throwaway cache: a listed
test that fails once passes, says FLAKY and is counted; one that fails
twice fails; a test not on the list fails on its first run, with no second.
A save keeps the failed first run's last lines (#109): --tail and the list
show them, from a local run or out of a CI job's log (tests/ci.py).
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
                           "open(f, 'w').write(str(n + 1))\nprint('run %%d ✓ out' %% n)\nsys.exit(1 if n < %d else 0)\n"
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
    need = lambda what, ok: ok or fails.append(what)
    need("the first run's output still passes through: %r" % out[:200], "run 0 ✓ out" in out and "run 1 ✓ out" in out)
    need("the FLAKY line names --tail: %r" % out[-300:], "flaky.py --tail %s" % rel(once) in out)
    t = json.load(open(os.path.join(tmp, "phosphor", "flakes.json")))[rel(once)]
    need("the save keeps the failed run's lines: %r" % t.get("tail"), t.get("tail") == ["run 0 ✓ out"]
         and t.get("tail_from", "").startswith("local "))
    flaky = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "tests", "flaky.py")] + list(a),
                                      cwd=ROOT, env=env, capture_output=True, text=True)
    r = flaky("--tail", rel(once))
    need("--tail prints them: %r" % r.stdout, r.returncode == 0 and "run 0 ✓ out" in r.stdout)
    r = flaky("--tail", rel(twice))
    need("--tail on a test never saved says so: %r" % r.stdout, r.returncode == 1 and "no failed run" in r.stdout)
    r = flaky()
    need("the list shows the last lines under the test: %r" % r.stdout, "| run 0 ✓ out" in r.stdout)

    # a CI save: the lines between the step's command and flaky.py's marker
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import ci
    log = ["$ zellij --version", "zellij 0.45.1", "$ python3 tests/flaky.py python3 tests/x.py",
           "Traceback (most recent call last):", "JSONDecodeError: Expecting value",
           "--- tests/x.py failed (rc 1); it's in tests/flaky.json: once more",
           "FLAKY tests/x.py: failed, passed on its second run (python3 tests/x.py)"]
    need("ci.py cuts a CI save's first run out of the log: %r" % ci.first_run(log, "tests/x.py"),
         ci.first_run(log, "tests/x.py") == log[3:5])
    need("and finds none for a test the log didn't save", ci.first_run(log, "tests/y.py") is None)
    # a test that leaves a child holding the pipe: flaky.py goes on when the test ends
    import time
    lingers = os.path.join(tmp, "lingers.py")
    open(lingers, "w").write("import subprocess, sys\nsubprocess.Popen(['sleep', '30'])\nprint('left one')\n"
                             "sys.exit(0)\n")
    json.dump({rel(once): "fails once", rel(twice): "fails twice", rel(lingers): "leaves a child"}, open(lst, "w"))
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "flaky.py"), sys.executable, rel(lingers)],
                       cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    need("a child left holding the pipe doesn't hold flaky.py: %.1fs, %r" % (time.time() - t0, r.stdout[-200:]),
         r.returncode == 0 and time.time() - t0 < 10 and b"left one" in r.stdout)
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
