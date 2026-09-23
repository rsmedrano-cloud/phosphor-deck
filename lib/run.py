"""phosphor run - every program in the deck runs through this.

When the program ends (exit, q, a crash) the pane doesn't vanish or quietly
restart: it says so, in color, and asks. Enter opens it again, x closes the
tab. A mistyped exit costs one Enter; closing is always a decision. With
--reconnect (ssh tabs) a dropped link, ssh's own 255, retries by itself.
A program that froze (a resize it never answers, see hung.py) is closed and
the pane says so, with the same Enter to open it again.

    phosphor run [--name NAME] [--reconnect] [--wait S] [--alt] -- CMD ARGS...
"""
import os, shutil, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, AMB, RED, RST, getkey
import dlog, hung

def sane():
    """Whatever the program left behind: attributes, cursor, mouse modes."""
    sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l")
    sys.stdout.flush()
    subprocess.call(["stty", "sane"], stderr=subprocess.DEVNULL)

def banner(name, text, color):
    sys.stdout.write("\n" + color + "\x1b[7m %s " % name + RST + " " + color + text + RST + "\n\n")

def keys(*pairs):
    sys.stdout.write("   " + "      ".join(AMB + k + RST + "  " + FG + v + RST for k, v in pairs) + "\n")
    sys.stdout.flush()

def ask(rows=None, onlog=None):
    """Enter again, x close, f forget, l the log; rows: {screen row: answer} for taps."""
    if rows: sys.stdout.write("\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    try:
        while True:
            k = getkey(None)
            if isinstance(k, tuple):
                if rows and k[1] == 0 and k[4] and k[3] in rows: return rows[k[3]]
                continue
            if k in ("\r", "\n", "r"): return "again"
            if k in ("x", "X"): return "close"
            if rows and k in ("f", "F"): return "forget"
            if onlog and k in ("l", "L"): onlog()
    finally:
        if rows: sys.stdout.write("\x1b[?1006l\x1b[?1000l"); sys.stdout.flush()

def show_log(name):
    """l on an ended pane: the last lines phosphor logged for this tool."""
    lines = dlog.tail_for(name, 12)
    sys.stdout.write("\n" + DIM + "-- phosphor logs " + name.lower() + " " + "-" * 20 + RST + "\n")
    if lines:
        for l in lines: sys.stdout.write("  " + DIM + l + RST + "\n")
    else:
        sys.stdout.write("  " + DIM + "(nothing logged for %s yet)" % name + RST + "\n")
    sys.stdout.write("\n"); sys.stdout.flush()

def cursor_row():
    """Where the cursor is now (1-based), asking the terminal; None if it doesn't say."""
    import termios, tty, select, re
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        return None
    try:
        tty.setraw(fd)
        sys.stdout.write("\x1b[6n"); sys.stdout.flush()
        data = b""
        while select.select([fd], [], [], 0.5)[0]:
            data += os.read(fd, 32)
            if b"R" in data: break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    m = re.search(rb"\x1b\[(\d+);\d+R", data)
    return int(m.group(1)) if m else None

def closing(name):
    """The tab this pane is the last of, if the profile brings it back."""
    if not os.environ.get("ZELLIJ"): return None
    try:
        import tabs
        tab, panes = tabs.mine()
        return tab if tab and panes == 1 and tabs.kept(tab) else None
    except Exception:
        dlog.event(name, "closing-check-failed")
        return None

def watch(child):
    """Wait for the program; close it if it froze. Returns (exit code, froze)."""
    try:
        tty = os.stat("/proc/self/fd/0").st_rdev if os.isatty(0) else None
    except OSError:
        tty = None
    after = float(os.environ.get("PHOSPHOR_HANG_SECONDS", "20"))
    w = hung.Watch(child.pid, tty, after) if tty is not None and after > 0 else None
    while True:
        try:
            return child.wait(timeout=min(3.0, max(after / 2, 0.2)) if w else None), False
        except subprocess.TimeoutExpired:
            pass
        pid = w.tick(time.monotonic())
        if pid is None: continue
        for sig in (signal.SIGTERM, signal.SIGKILL):     # frozen: TERM's handler may freeze too
            for p in {pid, child.pid}:
                try: os.kill(p, sig)
                except OSError: pass
            try:
                return child.wait(timeout=2), True
            except subprocess.TimeoutExpired:
                pass
        return child.wait(), True

def main():
    a = sys.argv[1:]
    name, reconnect, wait, alt = None, False, 0.0, False
    while a and a[0] != "--":
        o = a.pop(0)
        if o == "--name" and a: name = a.pop(0)
        elif o == "--reconnect": reconnect = True
        elif o == "--wait" and a: wait = float(a.pop(0))
        elif o == "--alt": alt = True
    if a and a[0] == "--": a.pop(0)
    if not a:
        print("usage: phosphor run [--name N] [--reconnect] [--wait S] [--alt] -- CMD ARGS..."); return 2
    name = name or os.path.basename(a[0]).upper()
    if wait: time.sleep(wait)          # some TUIs read the size once, before zellij settles it
    while True:
        if alt:
            # gping and ctop draw on the normal screen, where zellij keeps
            # scrollback of every redraw and touch-scrolling breaks the pane.
            sys.stdout.write("\x1b[?1049h"); sys.stdout.flush()
        # Like a shell: Ctrl-C and Ctrl-\ are for the program, not for us.
        prev = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGQUIT)}
        missing = froze = False
        broke, child = None, None
        if dlog.tracing(name): dlog.trace(name, "start: %s" % " ".join(a))
        try:
            child = subprocess.Popen(a, preexec_fn=lambda: [signal.signal(s, signal.SIG_DFL)
                                                            for s in (signal.SIGINT, signal.SIGQUIT)])
            rc, froze = watch(child)
        except (FileNotFoundError, PermissionError):
            rc, missing = 127, True
        except Exception as e:
            rc, broke = 1, e
            if child is not None and child.poll() is None:
                try: child.kill()
                except OSError: pass
        finally:
            for s, h in prev.items(): signal.signal(s, h)
        if alt:
            sys.stdout.write("\x1b[?1049l")
        sane()
        if dlog.tracing(name):
            dlog.trace(name, "rc=%s froze=%s missing=%s broke=%s" % (rc, froze, missing, bool(broke)))
        if reconnect and rc == 255:
            dlog.event(name, "dropped", "reconnecting in 3s")
            banner(name, "connection lost: reconnecting in 3s", AMB)
            keys(("x", "close this tab"))
            if getkey(3.0) in ("x", "X"): return 0
            continue
        again = "open it again"
        if froze:
            dlog.event(name, "hung")
            banner(name, "stopped responding, so it was closed", RED)
        elif missing:
            banner(name, "couldn't start: %s isn't installed" % os.path.basename(a[0]), RED)
            again = "try again"
        elif broke:
            dlog.crash(name, broke)
            banner(name, "phosphor run hit a problem watching it: see phosphor logs " + name.lower(), RED)
        else:
            if rc != 0: dlog.event(name, "exit", str(rc))
            what = ("you left %s" % name.lower()) if reconnect or a[0].endswith("ssh") else \
                   ("ended" + ("" if rc == 0 else " (exit %d)" % rc))
            banner(name, what, AMB if rc == 0 else RED)
        kept = closing(name)
        if not kept:
            keys(("Enter", again), ("x", "close this tab"), ("l", "see the log"))
            answer = ask(onlog=lambda: show_log(name))
        else:
            # it comes back after every restart: say so, and offer to stop that
            options = [("Enter", again, "again"), ("x", "close it for now (back after a restart)", "close"),
                       ("f", "close it and forget it: out of your profile", "forget")]
            for k, v, _ in options:
                sys.stdout.write("   " + AMB + "%-7s" % k + RST + FG + v + RST + "\r\n")
            sys.stdout.flush()
            below = cursor_row()
            rows = {below - len(options) + i: ans for i, (_, _, ans) in enumerate(options)} if below else {}
            sys.stdout.write("   " + AMB + "%-7s" % "l" + RST + FG + "see the log" + RST + "\r\n"); sys.stdout.flush()
            answer = ask(rows or {0: None}, onlog=lambda: show_log(name))
        if answer == "forget":
            import tabs
            err = tabs.forget(kept)
            if err:
                sys.stdout.write("   " + RED + err + RST + "\n"); sys.stdout.flush(); time.sleep(3)
            return 0
        if answer == "close":
            return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
