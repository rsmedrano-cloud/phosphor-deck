#!/usr/bin/env python3
"""The quarantine: tests known to fail now and then, run twice before
they fail a pipeline, and counted every time the second run saved one.

    python3 tests/flaky.py CMD ARGS...    run it; a listed test gets a second run
    python3 tests/flaky.py                the list, and how often each was saved
    python3 tests/flaky.py --tail TEST    the last lines of the run a second run saved

tests/flaky.json lists them, each with why it's there. A listed test that
fails, then passes, prints one line starting "FLAKY " and passes; one that
fails twice fails, as does any test not on the list. check.sh runs every
step through here; the zellij jobs run their listed tests through here.

The count: a run outside CI adds to it itself; tests/ci.py adds what each
job of a pipeline printed, once per job. It lives in the cache
($XDG_CACHE_HOME/phosphor/flakes.json), not the repo: the ones saved most
are the next to fix, and one never saved in months can leave the list.
With the count, the last lines of the first run that failed (#109): the
second run passing would otherwise leave nothing of why it failed.
"""
import collections, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.environ.get("FLAKY_LIST") or os.path.join(ROOT, "tests", "flaky.json")   # tests/flaky-check.py
COUNTS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                      "phosphor", "flakes.json")
TAIL = 30                       # lines of a failed first run kept with its count


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


def count(test, where, tail=None):
    """One more save for test; where (a CI job's id, or a local run's time)
    is counted once. tail: the last lines of the run that failed, kept
    (with where) until the next save brings its own."""
    c = counts()
    t = c.setdefault(test, {"saved": 0, "last": "", "seen": []})
    if where in t["seen"]:
        return
    t["seen"] = (t["seen"] + [where])[-50:]
    t["saved"] += 1
    t["last"] = time.strftime("%Y-%m-%d")
    if tail:
        t["tail"], t["tail_from"] = list(tail)[-TAIL:], where
    os.makedirs(os.path.dirname(COUNTS), exist_ok=True)
    tmp = COUNTS + ".tmp"
    json.dump(c, open(tmp, "w"), indent=1)
    os.replace(tmp, COUNTS)


def line(test, argv):
    return "FLAKY %s: failed, passed on its second run (%s); its first run: python3 tests/flaky.py --tail %s" % (
        test, " ".join(argv), test)


MARK = "it's in tests/flaky.json: once more"      # tests/ci.py finds the first run's end by it


def first(argv):
    """(rc, its last TAIL lines): the run, every line passed on as it comes,
    whole lines of bytes (never a glyph split in two). Done when the test
    ends, not when the pipe does: a server it left behind (zellij) may
    hold the pipe open for good."""
    import threading
    tail = collections.deque(maxlen=TAIL)
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = sys.stdout.buffer

    def read():
        for l in iter(p.stdout.readline, b""):
            out.write(l); out.flush()
            tail.append(l.decode("utf-8", "replace").rstrip("\n"))
    r = threading.Thread(target=read, daemon=True)
    r.start()
    rc = p.wait()
    r.join(2)                   # what it printed last is still in the pipe
    return rc, list(tail)


def run(argv):
    test = test_of(argv)
    if test not in listed():
        return subprocess.call(argv)
    rc, tail = first(argv)
    if rc == 0:
        return rc
    sys.stdout.write("\n--- %s failed (rc %d); %s\n" % (test, rc, MARK))
    sys.stdout.flush()
    rc = subprocess.call(argv)
    if rc == 0:
        print(line(test, argv))
        if not os.environ.get("CI"):
            count(test, "local %s" % time.strftime("%Y-%m-%dT%H:%M:%S"), tail)
    return rc


def show():
    c = counts()
    for test, why in sorted(listed().items()):
        t = c.get(test, {})
        print("  %-28s saved %3d   %s" % (test, t.get("saved", 0),
                                         ("last " + t["last"]) if t.get("last") else "never yet"))
        print("  %-28s %s" % ("", why))
        if t.get("tail"):
            print("  %-28s its last failed run (%s) ended:" % ("", t.get("tail_from", "")))
            for l in t["tail"][-8:]:
                print("  %-28s | %s" % ("", l))


def tail(test):
    t = counts().get(test.replace(os.sep, "/"), {})
    if not t.get("tail"):
        print("no failed run kept for %s (a save keeps one from now on)" % test)
        return 1
    print("%s, its last failed run (%s), saved by a second run:" % (test, t.get("tail_from", "")))
    print("\n".join(t["tail"]))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--tail"] and len(sys.argv) == 3:
        sys.exit(tail(sys.argv[2]))
    if sys.argv[1:]:
        sys.exit(run(sys.argv[1:]))
    show()
