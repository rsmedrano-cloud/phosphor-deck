#!/usr/bin/env python3
"""phosphor adjutant at any width: its pane is a share of SYS ("25%"), so
on a phone it can be a dozen columns. Every line it draws stays inside the
pane -- the bitmap face, the character one, and a message longer than the
pane -- instead of wrapping into the rows below. And a big pane doesn't
blow the face up: it stays at the size a Pi's 7" screen shows, centered.

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

# a big pane: the face stays at its cap and the box sits in the middle
cache = tempfile.mkdtemp()
open(os.path.join(cache, "events"), "w").close()
out = frames(200, 60, [], cache)
frame = out.split("\x1b[H")[-2] if out.count("\x1b[H") > 1 else out
lines = [ANSI.sub("", ln).rstrip("\r") for ln in frame.split("\n")]
box = [i for i, ln in enumerate(lines) if "\u256d" in ln or "\u2570" in ln]
pic = [ln for ln in lines if "\u2580" in ln]
if len(box) != 2:
    fails.append("200x60: no box drawn")
else:
    top, bot = box
    left = lines[top].index("\u256d")
    right = 200 - len(lines[top])
    if abs(left - right) > 1:
        fails.append("200x60: box not centered across (%d left, %d right)" % (left, right))
    if abs(top - (59 - bot)) > 1:
        fails.append("200x60: box not centered down (%d above, %d below)" % (top, 59 - bot))
    widest = max((ln.count("\u2580") for ln in pic), default=0)
    if not pic or widest > 28:
        fails.append("200x60: the face is %d columns wide (cap 28)" % widest)

# the Pi's own SYS pane (115x45 screen, 25%): the box still fills it
out = frames(27, 18, [], cache)
frame = out.split("\x1b[H")[-2] if out.count("\x1b[H") > 1 else out
lines = [ANSI.sub("", ln).rstrip("\r") for ln in frame.split("\n")]
if not lines[0].startswith("\u256d") or len(lines[0]) != 27:
    fails.append("27x18: the box no longer fills the pane")

if fails:
    print("\n".join(fails))
    sys.exit(1)
print("ok: the adjutant stays inside its pane from 8 to 90 columns, capped and centered at 200")
