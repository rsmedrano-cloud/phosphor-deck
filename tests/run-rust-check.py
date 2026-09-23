#!/usr/bin/env python3
"""rust/run (the optional Rust phosphor-run) in a real pty -- not mocks,
the actual compiled binary, the same way tests/hang-check.py already
exercises the Python one. Needs a Rust toolchain (builds the binary if it
isn't there yet); skips with a clear message if `cargo` isn't installed,
same spirit as tests that need zellij or docker.

    python3 tests/run-rust-check.py

Not in tests/check.sh: CI's images have no Rust toolchain (see
CONTRIBUTING.md and rust/run/README.md). Run this by hand after touching
rust/run.
"""
import fcntl, os, pty, select, shutil, struct, subprocess, sys, tempfile, termios, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRATE = os.path.join(ROOT, "rust", "run")
BIN = os.path.join(CRATE, "target", "debug", "phosphor-run")
# Every case below makes phosphor-run log real events (a hang, a crash, a
# dropped link) -- point PHOSPHOR_CACHE at a throwaway dir for the whole
# run, never the real ~/.cache/phosphor/deck.log.
CACHE = tempfile.mkdtemp(prefix="run-rust-check-")

if not shutil.which("cargo") and not os.path.exists(BIN):
    print("no cargo and no build yet: skipping (see rust/run/README.md)")
    sys.exit(0)
if not os.path.exists(BIN):
    r = subprocess.run(["cargo", "build"], cwd=CRATE, capture_output=True, text=True)
    if r.returncode != 0:
        print("cargo build failed:\n" + r.stderr[-2000:]); sys.exit(1)

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)


def run(args, env_extra=None, cwd=None):
    """A real pty around the binary; returns (pid, fd) to drive."""
    env = dict(os.environ, PHOSPHOR_CACHE=CACHE, **(env_extra or {}))
    pid, fd = pty.fork()
    if pid == 0:
        if cwd: os.chdir(cwd)
        os.execve(BIN, [BIN] + args, env)
    return pid, fd


def read_until(fd, needle, timeout=5.0):
    out, end = b"", time.time() + timeout
    while time.time() < end:
        if select.select([fd], [], [], 0.2)[0]:
            try: out += os.read(fd, 4096)
            except OSError: break
        if needle.encode() in out:
            return out, True
    return out, False


def cleanup(pid):
    try: os.killpg(pid, 9)
    except OSError: pass
    try: os.waitpid(pid, 0)
    except OSError: pass


# 1. A normal, fast-exiting program: banner, Enter reopens it, x closes.
pid, fd = run(["--name", "PROBE", "--", "sh", "-c", "exit 0"])
try:
    out, seen = read_until(fd, "ended")
    check("shows the ended banner", seen)
    os.write(fd, b"\r")
    out2, seen2 = read_until(fd, "ended", timeout=5.0)
    check("Enter relaunches it (banner shows again)", seen2)
    os.write(fd, b"x")
    time.sleep(0.5)
    try:
        wpid, _status = os.waitpid(pid, os.WNOHANG)
        dead = wpid == pid
    except ChildProcessError:
        dead = True
    check("x ends the process", dead)
finally:
    cleanup(pid)

# 2. A command that isn't installed.
pid, fd = run(["--name", "PROBE", "--", "this-does-not-exist-anywhere"])
try:
    out, seen = read_until(fd, "isn't installed")
    check("a missing program says so, not a crash", seen)
finally:
    cleanup(pid)

# 3. --reconnect: an ssh-style 255 exit gets "reconnecting", not "ended".
pid, fd = run(["--name", "PROBE", "--reconnect", "--", "sh", "-c", "exit 255"])
try:
    out, seen = read_until(fd, "reconnecting in 3s")
    check("--reconnect treats exit 255 as a dropped link", seen)
    os.write(fd, b"x")
    time.sleep(0.3)
finally:
    cleanup(pid)

# 4. Hang detection, in a real pty, resized -- same three shapes as
# tests/hang-check.py (frozen: blocks SIGWINCH and sleeps; healthy: takes
# the resize; busy: blocks it but keeps using CPU, must NOT be closed).
FROZEN = "import signal,time; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGWINCH}); time.sleep(60)"
HEALTHY = "import signal,time; signal.signal(signal.SIGWINCH, lambda *a: None)\nwhile True: time.sleep(60)"
BUSY = ("import signal,time; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGWINCH})\n"
        "t=time.time()\nwhile time.time()-t<60: sum(range(10000))")

def hang_case(code, seconds=6):
    env = {"PHOSPHOR_HANG_SECONDS": "0.6"}
    pid, fd = run(["--name", "PROBE", "--", sys.executable, "-c", code], env_extra=env)
    out, end, resized = b"", time.time() + seconds, False
    while time.time() < end:
        if not resized and time.time() > end - seconds + 0.5:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 40, 0, 0)); resized = True
        if select.select([fd], [], [], 0.1)[0]:
            try: out += os.read(fd, 4096)
            except OSError: break
        if b"stopped responding" in out: break
    cleanup(pid)
    return b"stopped responding" in out

check("a frozen program (blocks SIGWINCH) is closed", hang_case(FROZEN))
check("a healthy program (answers SIGWINCH) is left alone", not hang_case(HEALTHY))
check("a busy program (blocks SIGWINCH but uses CPU) is left alone", not hang_case(BUSY))

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
