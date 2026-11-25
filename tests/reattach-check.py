#!/usr/bin/env python3
"""deck goes back in after a restart even if zellij drops the screen as too
slow once, and a detach right after a restart stays out (#107).

    python3 tests/reattach-check.py

Both exit 0; only the goodbye the client leaves in zellij's log tells them
apart. That text is checked against a real zellij 0.45.1 log
(tests/fixtures/zellij-goodbyes-0.45.1.txt); attach()'s loop runs in a pty
against a fake zellij that writes those goodbyes to a log of its own
($TMPDIR), in a temp HOME. No zellij runs: a real drop takes ~100 s.
"""
import os, pty, select, shutil, signal, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

FIXTURE = open(os.path.join(HERE, "fixtures/zellij-goodbyes-0.45.1.txt")).read()
lines = FIXTURE.splitlines(keepends=True)
BYE = next(l for l in lines if "Bye from Zellij!" in l)
start = next(i for i, l in enumerate(lines) if l.rstrip().endswith("lib.rs:1620:"))
end = next(i for i, l in enumerate(lines) if "terminal emulator" in l)
DROP = "".join(lines[start:end + 1])          # names the session `probe`

# ── dropped(): the goodbyes, as zellij writes them ─────────────
tmp = tempfile.mkdtemp(prefix="reattach-")
os.environ["TMPDIR"] = tmp
import session
log = session.zlog()
os.makedirs(os.path.dirname(log))
def logged(text):
    open(log, "w").write(text)
need("no log: not a drop", not session.dropped("probe", 0))
logged(FIXTURE)
need("the real 0.45.1 drop is one", session.dropped("probe", 0))
need("a drop naming another session isn't ours", not session.dropped("deck", 0))
need("no size noted (no attach after a restart): not a drop", not session.dropped("probe", None))
need("only what was logged since counts", not session.dropped("probe", len(FIXTURE.encode())))
logged(DROP + BYE)
need("a detach after a drop: the detach is the last goodbye", not session.dropped("probe", 0))
logged(BYE)
need("the real 0.45.1 detach isn't a drop", not session.dropped("probe", 0))
logged(DROP)
need("the log rotated meanwhile (smaller than noted): all of it is new", session.dropped("probe", 10**7))
shutil.rmtree(tmp)

# ── attach(): back in after a drop, out after a detach ─────────
FAKE = r'''#!%s
import os, sys
H = os.environ["HOME"]
log = os.path.join(os.environ["TMPDIR"], "zellij-%%d" %% os.getuid(), "zellij-log", "zellij.log")
marker = os.path.join(H, ".cache/phosphor/restarting")
a = sys.argv[1:]
if a[:1] == ["list-sessions"]:
    if os.path.exists(marker): os.remove(marker)      # the new deck is up
    print("deck"); sys.exit(0)
if a[:1] == ["attach"]:
    steps = open(H + "/steps").read().split()
    step = steps.pop(0) if steps else "detach"
    open(H + "/steps", "w").write(" ".join(steps))
    open(H + "/attaches", "a").write(step + "\n")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    if step == "nosession":                            # listed, and yet zellij's attach misses it (#136)
        print("No session with the name '%%s' found!" %% a[1]); sys.exit(1)
    if step == "restart":                              # phosphor restart kicks everyone out
        os.makedirs(os.path.dirname(marker), exist_ok=True); open(marker, "w").close()
    elif step.startswith("drop"):
        sess = step.partition(":")[2] or a[1]
        open(log, "a").write(%r.replace("zellij attach probe`", "zellij attach %%s`" %% sess))
    else:
        open(log, "a").write(%r)
    sys.exit(0)
sys.exit(0)
''' % (sys.executable, DROP, BYE)

PROFILE = '''
[deck]
session = "deck"

[[tabs]]
name  = "SH"
panes = [ { cmd = "" } ]
'''

def run(steps):
    """`deck` in a pty; returns (attaches, exit code, what it printed)."""
    home = tempfile.mkdtemp(prefix="reattach-")
    try:
        for d in (".local/bin", ".local/share/phosphor", ".config/phosphor", "t"):
            os.makedirs(os.path.join(home, d))
        open(os.path.join(home, ".local/share/phosphor/.welcomed"), "w").close()
        open(os.path.join(home, ".config/phosphor/deck.toml"), "w").write(PROFILE)
        open(os.path.join(home, "steps"), "w").write(" ".join(steps))
        zj = os.path.join(home, ".local/bin/zellij")
        open(zj, "w").write(FAKE); os.chmod(zj, 0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
        env.update(HOME=home, TMPDIR=os.path.join(home, "t"), TERM="xterm-256color",
                   XDG_CONFIG_HOME=os.path.join(home, ".config"),
                   XDG_CACHE_HOME=os.path.join(home, ".cache"),
                   XDG_DATA_HOME=os.path.join(home, ".local/share"),
                   PHOSPHOR_PROFILE=os.path.join(home, ".config/phosphor/deck.toml"),
                   PATH=os.path.join(home, ".local/bin") + os.pathsep + "/usr/bin:/bin")
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, "-c",
                      "import sys; sys.path.insert(0, %r)\nimport session\nsys.exit(session.attach([]))"
                      % os.path.join(ROOT, "lib")], env)
        out, deadline = b"", time.time() + 30
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try: data = os.read(fd, 65536)
                except OSError: break
                if not data: break
                out += data
        st, gone = None, time.time() + 5     # the pty closes a moment before it exits
        while st is None and time.time() < gone:
            p, s = os.waitpid(pid, os.WNOHANG)
            if p: st = s
            else: time.sleep(0.05)
        if st is None:
            os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        rc = os.WEXITSTATUS(st) if st is not None and os.WIFEXITED(st) else None
        try: attaches = open(os.path.join(home, "attaches")).read().split()
        except OSError: attaches = []
        return attaches, rc, out.decode("utf-8", "replace")
    finally:
        shutil.rmtree(home, ignore_errors=True)

def case(what, steps, want):
    attaches, rc, out = run(steps)
    if not need("%s: attaches %s, wanted %s (exit %s)\n%s" % (what, attaches, want, rc, out[-600:]),
                attaches == want and rc == 0):
        return ""
    return out

out = case("a drop right after a restart: back in, then a detach leaves",
           ["restart", "drop", "detach"], ["restart", "drop", "detach"])
need("it says why it goes back in", out.count("going back in") == 1)
case("a detach right after a restart stays out", ["restart", "detach"], ["restart", "detach"])
case("a screen that's always too slow: two tries back, then out",
     ["restart", "drop", "drop", "drop", "detach"], ["restart", "drop", "drop", "drop"])
case("a drop with no restart before it: out, as before", ["drop", "detach"], ["drop"])
out = case("the new deck not there yet for zellij's attach: back in (#136)",
           ["restart", "nosession", "detach"], ["restart", "nosession", "detach"])
need("it says why it goes back in (#136)", "isn't ready" in out)
attaches, rc, _ = run(["restart", "nosession", "nosession", "nosession", "detach"])
need("never there for the attach: two tries back, then out with zellij's error (#136; %s, exit %s)"
     % (attaches, rc), attaches == ["restart", "nosession", "nosession", "nosession"] and rc == 1)
attaches, rc, _ = run(["nosession", "detach"])
need("no session with no restart before it: out, as before (%s, exit %s)" % (attaches, rc),
     attaches == ["nosession"] and rc == 1)
case("another session's drop: out", ["restart", "drop:other", "detach"], ["restart", "drop:other"])

if fails:
    print("FAIL reattach-check:"); [print("  -", f) for f in fails]; sys.exit(1)
print("reattach-check: ok")
