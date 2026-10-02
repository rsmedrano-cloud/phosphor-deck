#!/usr/bin/env python3
"""A screen with no keyboard (a touch tablet) is never stuck: every way out
of a pane that waits for an answer takes a tap.

    python3 tests/touch-check.py

Found on a 7" touch screen (#48): a tap on the tab bar's + opened the menu
in a new "Tab #5", and the only way to close it was q or Esc; a pane that
ended asked for Enter or x, and only a kept tab's prompt took a tap.
"""
import os, sys, pty, select, time, struct, fcntl, termios, tempfile, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

fail = []
def check(what, cond):
    if not cond: fail.append(what)

TMP = tempfile.mkdtemp()
ENV = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
ENV.update(TERM="xterm-256color", PHOSPHOR_CACHE=os.path.join(TMP, "cache"),
           PHOSPHOR_DATA=os.path.join(TMP, "data"), PHOSPHOR_HANG_SECONDS="0",
           PHOSPHOR_PROFILE=os.path.join(ROOT, "profiles", "example.toml"))

CPR_ROW = 10        # where the test's "terminal" says the cursor is when asked

def session(argv, taps, wait=1.0):
    """Run phosphor in a pty, answer its cursor query, tap (x, y)s. (ended, output)."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor")] + argv, ENV)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    out = b""
    def drain(t):
        nonlocal out
        end = time.time() + t
        while time.time() < end:
            if select.select([fd], [], [], 0.05)[0]:
                try: chunk = os.read(fd, 65536)
                except OSError: return
                out += chunk
                if b"\x1b[6n" in chunk:
                    os.write(fd, b"\x1b[%d;1R" % CPR_ROW)
    drain(wait)
    for x, y in taps:
        os.write(fd, ("\x1b[<0;%d;%dM\x1b[<0;%d;%dm" % (x, y, x, y)).encode()); drain(0.6)
    ended = os.waitpid(pid, os.WNOHANG)[0] != 0
    if not ended:
        os.kill(pid, 9); os.waitpid(pid, 0)
    return ended, re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.decode("utf-8", "replace"))

# a pane that ended, in a tab the profile doesn't keep: Enter, x, l -- one row
# each, the last of them just above the cursor
run = ["run", "--name", "TOUCH", "--", "true"]
again, close, log = CPR_ROW - 3, CPR_ROW - 2, CPR_ROW - 1
ended, out = session(run, [(6, close)])
check("ended pane: a tap on 'close this tab' closes it (%s)" % out[-200:], ended)
ended, out = session(run, [(6, log)])
check("ended pane: a tap on 'see the log' shows it and stays", not ended and "phosphor logs touch" in out)
ended, out = session(run, [(6, again)])
check("ended pane: a tap on 'open it again' runs it again", not ended and out.count("close this tab") >= 2)
ended, _ = session(run, [(6, 1)])
check("ended pane: a tap elsewhere does nothing", not ended)

# the + menu: its close row is a tap target, not only a q/Esc hint
import newtab, deckconf
os.environ["PHOSPHOR_PROFILE"] = ENV["PHOSPHOR_PROFILE"]
prof, _ = deckconf.load()
rows, acts = newtab.render(newtab.entries(prof), 0, False, 80)
check("the + menu has a 'close' row", "close" in acts)
y = acts.index("close") + 1 if "close" in acts else 1
ended, out = session(["new"], [(4, y)])
check("the + menu: a tap on 'close this tab' closes it (%s)" % out[-200:], ended)

if fail:
    print("touch-check FAILED:\n  " + "\n  ".join(fail)); sys.exit(1)
print("touch-check ok")
