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

def main():
    if not zjprobe.zellij():
        print("no zellij here: skipped"); return 0
    with zjprobe.Probe(PROFILE) as z:
        z.pump(2)
        env = dict(z.env, TERM="xterm-mono")     # from outside the deck, as over ssh: the profile names the session
        # this process's own zellij calls go through z (the probe's socket), never mirror.find
        ai = next("terminal_%d" % p["id"] for p in json.loads(z.action("list-panes", "-a", "-j"))
                  if not p["is_plugin"] and p["tab_name"] == "AI")
        dump = lambda: z.action("dump-screen", "-p", ai)
        z.action("write-chars", "-p", ai, "echo hidden-$((6*7))\n")
        z.pump(1)

        r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "mirror", "--tab", "ai", "--once"],
                           env=env, capture_output=True, text=True, timeout=30)
        need("--once shows a tab nobody looks at (any case)", r.returncode == 0 and "hidden-42" in r.stdout)
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
        need("a key reaches the pane", s.wait(lambda: b"typed-5" in s.out) and "typed-5" in dump())
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
    for f in fails:
        print("FAIL:", f)
    print("mirror-check", "ok" if not fails else "FAILED")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
