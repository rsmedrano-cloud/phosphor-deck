#!/usr/bin/env python3
"""The quarantine: tests known to fail now and then, run twice before
they fail a pipeline, and counted every time the second run saved one.

    python3 tests/flaky.py CMD ARGS...    run it; a listed test gets a second run
    python3 tests/flaky.py                the list, and how often each was saved

tests/flaky.json lists them, each with why it's there. A listed test that
fails, then passes, prints one line starting "FLAKY " and passes; one that
fails twice fails, as does any test not on the list. check.sh runs every
step through here; the zellij jobs run their listed tests through here.

The count: a run outside CI adds to it itself; tests/ci.py adds what each
job of a pipeline printed, once per job. It lives in the cache
($XDG_CACHE_HOME/phosphor/flakes.json), not the repo: the ones saved most
are the next to fix, and one never saved in months can leave the list.
"""
import json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.environ.get("FLAKY_LIST") or os.path.join(ROOT, "tests", "flaky.json")   # tests/flaky-check.py
COUNTS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                      "phosphor", "flakes.json")


def listed():
    return json.load(open(LIST))


def test_of(argv):
    """The tests/*.py a command runs, as flaky.json names it, or None."""
    for a in argv:
        p = os.path.relpath(os.path.abspath(a), ROOT)
        if p.startswith("tests" + os.sep) and p.endswith(".py"):
            return p.replace(os.sep, "/")
    return None


def counts():
    try:
        return json.load(open(COUNTS))
    except (OSError, ValueError):
        return {}


def count(test, where):
    """One more save for test; where (a CI job's id, or a local run's time)
    is counted once."""
    c = counts()
    t = c.setdefault(test, {"saved": 0, "last": "", "seen": []})
    if where in t["seen"]:
        return
    t["seen"] = (t["seen"] + [where])[-50:]
    t["saved"] += 1
    t["last"] = time.strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(COUNTS), exist_ok=True)
    tmp = COUNTS + ".tmp"
    json.dump(c, open(tmp, "w"), indent=1)
    os.replace(tmp, COUNTS)


def line(test, argv):
    return "FLAKY %s: failed, passed on its second run (%s)" % (test, " ".join(argv))


def run(argv):
    rc = subprocess.call(argv)
    test = test_of(argv)
    if rc == 0 or test not in listed():
        return rc
    sys.stdout.write("\n--- %s failed (rc %d); it's in tests/flaky.json: once more\n" % (test, rc))
    sys.stdout.flush()
    rc = subprocess.call(argv)
    if rc == 0:
        print(line(test, argv))
        if not os.environ.get("CI"):
            count(test, "local %s" % time.strftime("%Y-%m-%dT%H:%M:%S"))
    return rc


def show():
    c = counts()
    for test, why in sorted(listed().items()):
        t = c.get(test, {})
        print("  %-28s saved %3d   %s" % (test, t.get("saved", 0),
                                         ("last " + t["last"]) if t.get("last") else "never yet"))
        print("  %-28s %s" % ("", why))


if __name__ == "__main__":
    if sys.argv[1:]:
        sys.exit(run(sys.argv[1:]))
    show()
