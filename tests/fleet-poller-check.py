#!/usr/bin/env python3
"""fleet's poller picks a Rust binary when one is installed, and falls back
to its own Python thread otherwise -- nothing breaks for an install without
a Rust toolchain. Once running, RustPoller.tick() (called every redraw
frame) relaunches it after a crash, hot-reloads it the moment the binary on
disk changes (a rebuild), and gives up on Rust -- falling back to the
Python thread -- after a real crash loop. The wiring test (start_poller())
patches deckconf.exe/subprocess.Popen/threading.Thread; the tick() tests
spawn real, tiny, disposable scripts so a "died"/"still running" verdict is
never guessed.

    python3 tests/fleet-poller-check.py
"""
import os, stat, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import fleet

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)


# ---- start_poller(): the wiring, nothing real spawned -----------------

class FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.terminated = False
    def terminate(self):
        self.terminated = True

real_popen = fleet.subprocess.Popen
real_exe = fleet.deckconf.exe
real_thread = fleet.threading.Thread
real_getmtime = fleet.os.path.getmtime

def reset():
    fleet.DEMO = False
    fleet.subprocess.Popen = real_popen
    fleet.deckconf.exe = real_exe
    fleet.threading.Thread = real_thread
    fleet.os.path.getmtime = real_getmtime

try:
    reset()
    spawned = []
    fleet.deckconf.exe = lambda name: "/home/x/.local/bin/phosphor-fleet-poll" if name == "phosphor-fleet-poll" else None
    fleet.subprocess.Popen = lambda argv, **kw: (spawned.append(argv), FakeProc(4242))[1]
    fleet.os.path.getmtime = lambda p: 1.0
    threads_started = []
    fleet.threading.Thread = lambda **kw: type("T", (), {"start": lambda self: threads_started.append(kw)})()
    rp = fleet.start_poller()
    check("spawns the rust binary found by deckconf.exe", spawned == [["/home/x/.local/bin/phosphor-fleet-poll"]])
    check("returns a RustPoller wrapping its Popen", rp is not None and rp.proc.pid == 4242)
    check("never starts the python poller thread", threads_started == [])

    reset()
    fleet.deckconf.exe = lambda name: None
    threads_started = []
    fleet.threading.Thread = lambda **kw: type("T", (), {"start": lambda self: threads_started.append(kw)})()
    rp = fleet.start_poller()
    check("not installed: falls back to the python poller thread", len(threads_started) == 1
          and threads_started[0].get("target") is fleet.poller)
    check("not installed: nothing to tick/stop", rp is None)

    reset()
    fleet.DEMO = True
    fleet.deckconf.exe = lambda name: "/home/x/.local/bin/phosphor-fleet-poll"
    spawned = []
    fleet.subprocess.Popen = lambda argv, **kw: (spawned.append(argv), FakeProc(1))[1]
    threads_started = []
    fleet.threading.Thread = lambda **kw: type("T", (), {"start": lambda self: threads_started.append(kw)})()
    rp = fleet.start_poller()
    check("demo mode never spawns the rust binary", spawned == [])
    check("demo mode always uses the python poller", len(threads_started) == 1)

    reset()
    fleet.deckconf.exe = lambda name: "/home/x/.local/bin/phosphor-fleet-poll"
    fleet.os.path.getmtime = lambda p: 1.0
    def raising(argv, **kw): raise OSError("no exec permission")
    fleet.subprocess.Popen = raising
    threads_started = []
    fleet.threading.Thread = lambda **kw: type("T", (), {"start": lambda self: threads_started.append(kw)})()
    rp = fleet.start_poller()
    check("a broken rust binary still falls back to the python thread", len(threads_started) == 1)
    check("start_poller() doesn't raise", rp is not None and rp.gave_up)
finally:
    reset()


# ---- RustPoller.tick(): real, disposable scripts -----------------------

def script(body):
    """A tiny executable shell script at a fresh path; returns its path."""
    fd, path = tempfile.mkstemp(prefix="fleet-poll-fake-", suffix=".sh")
    os.write(fd, ("#!/bin/sh\n" + body).encode())
    os.close(fd)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path

def wait_dead(proc, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return True
        time.sleep(0.02)
    return False

try:
    reset()
    # 1. A crash: tick() notices it died and relaunches the same binary.
    p = script("exit 1\n")
    rp = fleet.RustPoller(p)
    try:
        first_pid = rp.proc.pid
        check("wait_dead sees the fast-exiting script really die", wait_dead(rp.proc))
        rp.tick()
        check("tick() relaunches after a crash", rp.proc is not None and rp.proc.pid != first_pid)
        check("a genuine restart doesn't count as a rebuild", not rp.gave_up)
    finally:
        rp.stop()
        os.unlink(p)

    # 2. A real crash loop: 4+ deaths inside RAPID_WINDOW gives up on Rust,
    #    falling back to the python thread -- the panel keeps updating.
    threads_started = []
    fleet.threading.Thread = lambda **kw: type("T", (), {"start": lambda self: threads_started.append(kw)})()
    p = script("exit 1\n")
    rp = fleet.RustPoller(p)
    try:
        for _ in range(fleet.RustPoller.MAX_RAPID_FAILS + 2):
            wait_dead(rp.proc)
            rp.tick()
            if rp.gave_up:
                break
        check("a real crash loop gives up on rust", rp.gave_up)
        check("giving up starts the python poller thread",
              len(threads_started) == 1 and threads_started[0].get("target") is fleet.poller)
    finally:
        if rp.proc is not None:
            rp.stop()
        os.unlink(p)
    fleet.threading.Thread = real_thread

    # 3. A rebuild: the binary's mtime changes on disk (a real cargo build,
    #    for real) while the old process is still alive -- tick() ends it
    #    and starts the new one, no crash needed.
    p = script("sleep 5\n")
    rp = fleet.RustPoller(p)
    try:
        old_proc = rp.proc
        check("the first one is actually still running", old_proc.poll() is None)
        time.sleep(0.05)
        os.utime(p, None)  # a fresh mtime, as a rebuild would leave
        rp.tick()
        check("tick() ends the old process on a rebuild", wait_dead(old_proc))
        check("tick() starts a new one with a different pid", rp.proc is not None and rp.proc.pid != old_proc.pid)
        check("hot-reloading a live process isn't a crash", rp.rapid_fails == 0 and not rp.gave_up)
    finally:
        rp.stop()
        os.unlink(p)

    # 4. Steady state: no death, no mtime change -- tick() is a no-op
    #    (doesn't needlessly relaunch a perfectly healthy poller).
    p = script("sleep 5\n")
    rp = fleet.RustPoller(p)
    try:
        pid = rp.proc.pid
        rp.tick(); rp.tick(); rp.tick()
        check("a healthy, unchanged binary is left running", rp.proc.pid == pid)
    finally:
        rp.stop()
        os.unlink(p)
finally:
    reset()

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
