#!/usr/bin/env python3
"""phosphor mirror against a throwaway zellij: it shows a pane of a tab
nobody is looking at, with no color, takes keys into it (not with --view),
leaves on Ctrl-], and a screen that stops reading doesn't make it pile up
output: it waits for the write, then paints what the pane says now."""
import json, os, pty, select, signal, struct, fcntl, subprocess, sys, termios, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "lib"))
import zjprobe
import mirror

PROFILE = '''
[deck]
session = "probe"

[[tabs]]
name  = "SH"
panes = [ { cmd = "" } ]

[[tabs]]
name  = "AI"
panes = [ { cmd = "" } ]
'''

fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

# ── the text it shows ──────────────────────────────────────────
need("fold: a long line wraps", mirror.fold("abcdefgh", 3) == ["abc", "def", "gh"])
need("fold: a rule is cut, not wrapped", mirror.fold("─" * 10, 4) == ["─" * 4])
need("fold: a wide character counts two", mirror.fold("日本語", 4) == ["日本", "語"])
need("view: the bottom, trailing blanks gone", mirror.view("a\nb\nc\n\n  \n", 10, 2) == ["b", "c"])
need("head: fits the width", len(mirror.head("AI", 30, False).replace(mirror.INV, "").replace(mirror.RST, "")) == 30)

class Screen:
    """phosphor mirror in a pty of its own: the slow screen."""
    def __init__(self, env, args, rows=10, cols=50):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "mirror"] + args, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.out = b""

    def pump(self, t):
        end = time.time() + t
        while time.time() < end:
            if self.fd is None:
                time.sleep(t); return
            if select.select([self.fd], [], [], 0.05)[0]:
                try: self.out += os.read(self.fd, 65536)
                except OSError: return

    def wait(self, cond, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond(): return True
            self.pump(0.2)
        return False

    def type(self, s):
        os.write(self.fd, s.encode() if isinstance(s, str) else s)

    def done(self, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.1)
            pid, st = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(st)
        os.kill(self.pid, signal.SIGKILL); os.waitpid(self.pid, 0)
        return None

def keys_vs_failed_reads(mode, tmp):
    """watch() in a pty of its own against a fake zellij, whose reads fail:
    'flaky' after the first frame (dump-screen), 'late' for the first two
    (list-panes). What's typed meanwhile must still reach the pane (#119).
    Returns (what the pane got, the screen's output, deck.log)."""
    got, log = os.path.join(tmp, mode + ".writes"), os.path.join(tmp, mode + ".log")
    pid, fd = pty.fork()
    if pid == 0:
        try:
            n = {"list-panes": 0, "dump-screen": 0}
            def zj(sess, *a, timeout=8):
                if a[0] in n:
                    n[a[0]] += 1
                if a[0] == "list-panes":
                    if mode == "late" and n["list-panes"] <= 2:
                        return None
                    return json.dumps([{"id": 7, "tab_name": "AI", "is_plugin": False, "is_focused": True}])
                if a[0] == "dump-screen":
                    return "hello\n" if mode != "flaky" or n["dump-screen"] == 1 else None
                if a[0] == "write":
                    with open(got, "a") as f:
                        f.write("%s %s\n" % (a[2], bytes(int(x) for x in a[3:]).decode()))
                    return ""
                return None
            mirror.zj, mirror.EVERY, mirror.dlog.LOG = zj, 0.3, log
            os._exit(mirror.watch("probe", {"tab": "AI"}, False) or 0)
        except BaseException:
            os._exit(3)
    s = Screen.__new__(Screen); s.pid, s.fd, s.out = pid, fd, b""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 50, 0, 0))
    seen = lambda: open(got).read() if os.path.exists(got) else ""
    if mode == "flaky":
        s.wait(lambda: b"can't read" in s.out, 5)     # the first frame painted, the next read failed
    else:
        s.wait(lambda: b"no tab AI" in s.out, 5)      # nothing found yet
    s.type("abc")
    s.wait(lambda: "abc" in seen(), 3)
    s.type(b"\x1d"); s.done()
    return seen(), s.out, open(log).read() if os.path.exists(log) else ""

def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        w, out, _ = keys_vs_failed_reads("flaky", tmp)
        need("a key typed while a read of the pane fails still reaches it (#119; screen saw %r)"
             % out[-120:], w == "terminal_7 abc\n")
        w, out, _ = keys_vs_failed_reads("late", tmp)
        need("a key typed before the pane is found waits for it (#119; screen saw %r)"
             % out[-120:], w == "terminal_7 abc\n")
    if not zjprobe.zellij():
        print("no zellij here: the rest skipped")
    else:
        against_zellij()
    for f in fails:
        print("FAIL:", f)
    print("mirror-check", "ok" if not fails else "FAILED")
    return 1 if fails else 0

def against_zellij():
    with zjprobe.Probe(PROFILE) as z:
        z.pump(2)
        env = dict(z.env, TERM="xterm-mono")     # from outside the deck, as over ssh: the profile names the session
        # this process's own zellij calls go through z (the probe's socket), never mirror.find
        def ai_pane():
            try: ps = json.loads(z.action("list-panes", "-a", "-j"))
            except ValueError: return None    # listed tabs before panes, once (#119)
            return next(("terminal_%d" % p["id"] for p in ps
                         if not p["is_plugin"] and p["tab_name"] == "AI"), None)
        z.wait(ai_pane, 15)
        ai = ai_pane()
        if not need("the probe lists the AI pane", ai):
            return
        dump = lambda: z.action("dump-screen", "-p", ai)
        z.action("write-chars", "-p", ai, "echo hidden-$((6*7))\n")
        # the pane's shell prints it in its own time (seconds, under check.sh's load)
        need("the pane printed what was written to it", z.wait(lambda: "hidden-42" in (dump() or ""), 20))

        r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "mirror", "--tab", "ai", "--once"],
                           env=env, capture_output=True, text=True, timeout=30)
        need("--once shows a tab nobody looks at (any case; exit %s, said %r)" % (r.returncode, r.stdout[-160:]),
             r.returncode == 0 and "hidden-42" in r.stdout)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "mirror"],
                           env=env, capture_output=True, text=True, timeout=30)
        need("no target: exit 2, the panes listed", r.returncode == 2 and "AI" in r.stderr and "SH" in r.stderr)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "mirror", "--tab", "NOPE", "--once"],
                           env=env, capture_output=True, text=True, timeout=30)
        need("--once on a missing tab: exit 1", r.returncode == 1 and "no tab NOPE" in r.stdout)

        # keys typed on the screen land in the pane; what it prints comes back
        s = Screen(env, ["--tab", "AI"])
        need("paints the pane", s.wait(lambda: b"hidden-42" in s.out))
        s.type("echo typed-$((2+3))\r")
        shown = s.wait(lambda: b"typed-5" in s.out, 20)
        landed = "typed-5" in (dump() or "")
        need("a key reaches the pane (in the pane: %s, back on the screen: %s)" % (landed, shown),
             shown and landed)
        need("no color on the screen", b"38;2;" not in s.out and b"38;5;" not in s.out)

        # a screen that stops reading: mirror waits on its write, nothing piles up
        z.action("write-chars", "-p", ai,
                 "i=0; while [ $i -lt 400 ]; do i=$((i+1)); echo flood-$i; sleep 0.02; done; echo flood-over\n")
        time.sleep(10)                                   # the screen reads nothing meanwhile
        before = len(s.out)
        s.pump(1.5)
        need("a stalled screen gets no backlog", len(s.out) - before < 16000)
        need("then the pane as it is now", s.wait(lambda: b"flood-over" in s.out[before:]))
        need("not every line it missed", s.out[before:].count(b"flood-") < 100)

        s.type(b"\x1d")
        need("Ctrl-] leaves, exit 0", s.done() == 0)

        # --view: watch only
        s = Screen(env, ["--tab", "AI", "--view"])
        need("--view paints", s.wait(lambda: b"flood-over" in s.out))
        s.type("echo never-$((1+1))\r")
        s.pump(2)
        need("--view sends no key", "never-2" not in dump())
        s.type("q")
        need("--view: q leaves", s.done() == 0)

        # the panel's EXIT closes its ssh: the pty goes away under mirror
        s = Screen(env, ["--tab", "AI", "--view"])
        need("paints before the hangup", s.wait(lambda: b"flood-over" in s.out))
        os.close(s.fd); s.fd = None
        log = os.path.join(env.get("PHOSPHOR_CACHE") or os.path.join(env["HOME"], ".cache", "phosphor"), "deck.log")
        code = s.done()
        tail = open(log, errors="replace").read()[-2000:] if os.path.exists(log) else ""
        need("a hangup ends it quietly (exit %s, no crash in deck.log)" % code,
             code == 0 and "crash" not in tail and "Traceback" not in tail)

if __name__ == "__main__":
    sys.exit(main())
