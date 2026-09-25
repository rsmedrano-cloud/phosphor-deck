#!/usr/bin/env python3
"""phosphor run closes a program that froze, and only that.

    python3 tests/hang-check.py

A frozen TUI keeps its last frame and looks alive (btop sat an hour on
"Terminal size too small"). Three programs in a real pty, resized:
one that blocks SIGWINCH and sleeps (frozen), one that takes it (healthy),
one that blocks it but keeps working (busy, not frozen).
"""
import os, pty, select, shutil, struct, fcntl, tempfile, termios, time, sys, threading
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Every case here makes phosphor run log a real event (a hang, in this
# file's case) -- point PHOSPHOR_CACHE at a throwaway dir for the whole
# run, never the real ~/.cache/phosphor/deck.log (found polluting it for
# real: 265 "PROBE hung" entries from however many times this ran here).
CACHE = tempfile.mkdtemp(prefix="hang-check-")

FROZEN = "import signal,time; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGWINCH}); time.sleep(60)"
HEALTHY = "import signal,time; signal.signal(signal.SIGWINCH, lambda *a: None)\nwhile True: time.sleep(60)"
BUSY = ("import signal,time; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGWINCH})\n"
        "t=time.time()\nwhile time.time()-t<60: sum(range(10000))")

def pane(code, seconds, result, key):
    env = dict(os.environ, PHOSPHOR_HANG_SECONDS="0.6", PHOSPHOR_CACHE=CACHE)
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "run",
                                   "--name", "PROBE", "--", sys.executable, "-c", code], env)
    out, end, resized = b"", time.time() + seconds, False
    while time.time() < end:
        if not resized and time.time() > end - seconds + 0.5:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 40, 0, 0)); resized = True
        if select.select([fd], [], [], 0.1)[0]:
            try: out += os.read(fd, 4096)
            except OSError: break
        if b"stopped responding" in out: break
    os.killpg(pid, 9); os.waitpid(pid, 0)          # the pane and whatever it started
    result[key] = b"stopped responding" in out

res = {}
th = [threading.Thread(target=pane, args=(c, 6, res, k))
      for k, c in (("frozen", FROZEN), ("healthy", HEALTHY), ("busy", BUSY))]
[t.start() for t in th]; [t.join() for t in th]
want = {"frozen": True, "healthy": False, "busy": False}
bad = [k for k in want if res.get(k) != want[k]]
shutil.rmtree(CACHE, ignore_errors=True)
if bad:
    print("wrong verdict for: " + ", ".join(bad), res); sys.exit(1)
