#!/usr/bin/env python3
"""phosphor adjutant at any width: its pane is a share of SYS ("25%"), so
on a phone it can be a dozen columns. Every line it draws stays inside the
pane -- the bitmap face, the character one, and a message longer than the
pane -- instead of wrapping into the rows below.

    python3 tests/adjutant-width-check.py
"""
import fcntl, os, pty, re, select, struct, sys, tempfile, termios, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
fails = []

def frames(cols, rows, args, cache):
    """What the adjutant draws in a cols x rows pty for about a second."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(PHOSPHOR_CACHE=cache, PHOSPHOR_DATA=cache, COLUMNS="", LINES="")
        os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "adjutant"] + args)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    buf, end = b"", time.time() + 1.2
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            try: buf += os.read(fd, 65536)
            except OSError: break
    os.kill(pid, 15)
    os.waitpid(pid, 0)
    return buf.decode("utf-8", "replace")

for face in ([], ["--face", "no-such-face"]):          # the bitmap one, then characters
    for cols in (8, 14, 20, 34, 90):
        cache = tempfile.mkdtemp()
        with open(os.path.join(cache, "events"), "w") as f:
            pass
        out = frames(cols, 14, face, cache)
        if not out:
            fails.append("%d cols %s: drew nothing" % (cols, face or "bitmap"))
            continue
        frame = out.split("\x1b[H")[-2] if out.count("\x1b[H") > 1 else out
        lines = [ANSI.sub("", ln).rstrip("\r") for ln in frame.split("\n")]
        wide = [len(ln) for ln in lines if len(ln) > cols]
        if wide:
            fails.append("%d cols %s: a line %d wide" % (cols, face and "characters" or "bitmap", max(wide)))

# a long message on a narrow pane: clipped, not wrapped
cache = tempfile.mkdtemp()
with open(os.path.join(cache, "events"), "w") as f:
    pass
pid, fd = pty.fork()
if pid == 0:
    os.environ.update(PHOSPHOR_CACHE=cache, PHOSPHOR_DATA=cache)
    os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "adjutant"])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 14, 12, 0, 0))
time.sleep(0.4)
with open(os.path.join(cache, "events"), "a") as f:
    f.write("SYS\t%s\n" % ("a long message " * 6))
buf, end = b"", time.time() + 2.4      # the static fades in under two seconds
while time.time() < end:
    if select.select([fd], [], [], 0.1)[0]:
        try: buf += os.read(fd, 65536)
        except OSError: break
os.kill(pid, 15)
os.waitpid(pid, 0)
frame = buf.decode("utf-8", "replace").split("\x1b[H")[-2]
lines = [ANSI.sub("", ln).rstrip("\r") for ln in frame.split("\n")]
if not any("a long" in ln for ln in lines):
    fails.append("12 cols with a message: the message never showed")
if any(len(ln) > 12 for ln in lines):
    fails.append("12 cols with a message: a line %d wide" % max(len(ln) for ln in lines))

if fails:
    print("\n".join(fails))
    sys.exit(1)
print("ok: the adjutant stays inside its pane from 8 to 90 columns")
