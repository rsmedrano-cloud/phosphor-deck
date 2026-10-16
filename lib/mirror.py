#!/usr/bin/env python3
"""phosphor mirror - one pane of the deck, for a screen too slow for zellij.

A screen that reads slower than zellij writes gets dropped ("client too
slow") and freezes: an e-ink panel takes a few KB a second, and one busy
tab sends megabytes a minute of redraws, mostly colors it can't show.
mirror never attaches a zellij client. It reads one pane's text from the
deck's session (`zellij action dump-screen`, which also works on a tab
nobody is looking at), sends the screen only the lines that changed, with
no color, and reads it again only once that write is through: a slow link
paces it by itself, and what changed meanwhile arrives as one paint.

What's typed on the screen goes to that pane (`zellij action write`), so a
conversation with an assistant works from a panel with a keyboard: typing
there is typing in the pane, as good as a shell wherever it runs.

    phosphor mirror --tab AI       the AI tab's focused pane, keys go to it
    phosphor mirror --pane 3       one pane by id (phosphor mirror lists them)
    phosphor mirror --tab AI --view   watch only: keys never reach the pane
    phosphor mirror --tab AI --once   one frame on stdout, for a script

The pane keeps its own size: a line wider than the screen wraps (a rule
of box lines is cut instead), and the screen shows the bottom of it,
where a prompt is. Ctrl-] leaves (also q and Ctrl-C with --view).
"""
import json, os, re, select, shutil, signal, subprocess, sys, termios, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf
import dlog
import proc
import ui

USAGE = "usage: phosphor mirror (--tab NAME | --pane ID) [--view | --once]"
EVERY = 1.0        # seconds between reads of the pane
ECHO = 0.3         # sooner after a key, so what was typed shows up
LEAVE = b"\x1d"    # Ctrl-]
MARK = re.compile(r"\s*●\d*$")     # an unread count (tabmark, mentions) on a tab's name
INV, RST = "\x1b[7m", "\x1b[0m"
RULES = set(" ─━│┃┄┅┈┉═║╌╍╭╮╯╰┌┐└┘├┤┬┴┼╴╶")


def session():
    """The deck's session: this pane's own, else the profile's."""
    return os.environ.get("ZELLIJ_SESSION_NAME") or \
        ((deckconf.load()[0] or {}).get("deck") or {}).get("session", "deck")


def zj(sess, *a, timeout=8):
    """A zellij action on sess, always named: never zellij's own guess of
    a session. stdout, or None when it failed."""
    z = proc.zellij()
    if not z:
        return None
    r = proc.run([z, "-s", sess, "action"] + list(a), timeout=timeout)
    return r.stdout if r.returncode == 0 else None


def panes(sess):
    """The session's terminal panes, as list-panes says them."""
    try:
        return [p for p in json.loads(zj(sess, "list-panes", "-a", "-j") or "[]")
                if not p.get("is_plugin")]
    except ValueError:
        return []


def tab_name(p):
    return MARK.sub("", p.get("tab_name") or "").strip()


def find(sess, tab=None, pane=None):
    """(pane id like terminal_3, the tab it's in), or None: the pane asked
    for, or the focused one of the tab (its name in any case, without an
    unread count)."""
    ps = panes(sess)
    if pane is not None:
        n = str(pane).replace("terminal_", "")
        hit = [p for p in ps if str(p["id"]) == n]
    else:
        hit = sorted((p for p in ps if tab_name(p).lower() == tab.lower()),
                     key=lambda p: (not p.get("is_focused"), p.get("is_floating", False), p["id"]))
    return ("terminal_%d" % hit[0]["id"], tab_name(hit[0])) if hit else None


def listing(sess):
    """Lines naming each pane, for `phosphor mirror` with nothing to show."""
    return ["  %-4s %-10s %s" % (p["id"], tab_name(p), p.get("title") or "") for p in panes(sess)]


def cols(ch):
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def fold(line, w):
    """line as screen lines no wider than w: wrapped, or cut when it's only
    box drawing (a rule, a frame's edge), which says nothing twice."""
    if not line:
        return [""]
    if set(line) <= RULES:
        w_line, n = [], 0
        for ch in line:
            if n + cols(ch) > w: break
            w_line.append(ch); n += cols(ch)
        return ["".join(w_line)]
    out, cur, n = [], [], 0
    for ch in line:
        c = cols(ch)
        if n + c > w:
            out.append("".join(cur)); cur, n = [], 0
        cur.append(ch); n += c
    out.append("".join(cur))
    return out


def view(text, w, rows):
    """The bottom of the pane's text as rows lines at most, w wide."""
    lines = [l.rstrip() for l in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    out = []
    for l in lines:
        out += fold(l, w)
    return out[-rows:] if rows > 0 else []


def head(name, w, watching):
    """The top line, reversed: which tab, and the way out."""
    left, right = " %s · mirror%s" % (name, " (view)" if watching else ""), "Ctrl-] leaves "
    gap = w - len(left) - len(right)
    return INV + (left + " " * gap + right if gap > 0 else ui.pad(left[:w], w)) + RST


def frame(sess, target, w, rows, watching):
    """The screen's lines for target (a tab name or a pane id), and the
    pane it found (None if it's gone)."""
    hit = find(sess, **target)
    if not hit:
        what = "tab %s" % target["tab"] if target.get("tab") else "pane %s" % target["pane"]
        return [head(str(target.get("tab") or target.get("pane")), w, watching),
                ui.cut("no %s in session %s: waiting for it" % (what, sess), w)], None
    pid, name = hit
    text = zj(sess, "dump-screen", "-p", pid)
    if text is None:
        return [head(name, w, watching), ui.cut("can't read %s: waiting" % pid, w)], None
    return [head(name, w, watching)] + view(text, w, rows - 1), pid


def raw_input():
    """Keys one by one, unechoed, Ctrl-C and Ctrl-Z included (they belong to
    the pane), output still turning \\n into \\r\\n. Returns the undo."""
    try:
        fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        return lambda: None
    new = termios.tcgetattr(fd)
    new[0] &= ~(termios.IXON | termios.ICRNL | termios.BRKINT | termios.ISTRIP | termios.INPCK)
    new[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
    new[6][termios.VMIN], new[6][termios.VTIME] = 1, 0
    termios.tcsetattr(fd, termios.TCSANOW, new)
    def undo():
        try: termios.tcsetattr(fd, termios.TCSANOW, old)
        except (termios.error, OSError): pass     # the screen hung up: nothing to put back
    return undo


def send(sess, pid, data):
    """data typed on the screen, into the pane."""
    zj(sess, "write", "-p", pid, *[str(b) for b in data])


def put(s):
    """Written whole before it returns: a slow screen's link holds it here,
    and the next read of the pane waits for it."""
    b, fd = s.encode(), sys.stdout.fileno()
    while b:
        b = b[os.write(fd, b):]


def hangup(*_):
    raise SystemExit("hangup")


def watch(sess, target, watch_only):
    """The screen that stays up (see the module's doc). Its start and why it
    ended go to deck.log: behind a forced ssh command nobody sees it."""
    size = shutil.get_terminal_size((0, 0))
    dlog.event("MIRROR", "start", "%s TERM=%s %dx%d%s" % (
        target.get("tab") or target.get("pane"), os.environ.get("TERM", "?"),
        size.columns, size.lines, " view" if watch_only else ""))
    signal.signal(signal.SIGHUP, hangup)
    signal.signal(signal.SIGTERM, hangup)
    undo = raw_input()
    put("\x1b[?1049h\x1b[?25l\x1b[2J")
    prev, last_size, why, due = None, None, "?", 0.0
    try:
        while True:
            now = time.time()
            if now >= due:
                w, rows = shutil.get_terminal_size((60, 20))
                lines, pid = frame(sess, target, w, rows, watch_only)
                fresh = (w, rows) != last_size
                paint = ui.paint(lines, None if fresh else prev)
                if paint:
                    put(paint)
                prev, last_size, due = lines, (w, rows), time.time() + EVERY
            r = select.select([sys.stdin], [], [], max(0.0, due - time.time()))[0]
            if not r:
                continue
            data = os.read(sys.stdin.fileno(), 4096)
            if not data:
                why = "end of input"; break
            if LEAVE in data or (watch_only and data[:1] in (b"q", b"\x03")):
                why = "key"; break
            if not watch_only and pid:
                send(sess, pid, data)
                due = min(due, time.time() + ECHO)
    except SystemExit as e:
        why = str(e) or "exit"
    except (BrokenPipeError, OSError) as e:
        why = "screen gone (%s)" % type(e).__name__
    except Exception:
        why = "crash"
        dlog.crash("MIRROR")
        raise
    finally:
        dlog.event("MIRROR", "end", why)
        undo()
        try: put("\x1b[?1049l\x1b[?25h\n")
        except OSError: pass
    return 0


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(USAGE); return 0
    target = {}
    for flag in ("--tab", "--pane"):
        if flag in a:
            i = a.index(flag)
            if i + 1 >= len(a):
                print(USAGE, file=sys.stderr); return 2
            target[flag[2:]] = a[i + 1]
    sess = session()
    if len(target) != 1:
        print(USAGE, file=sys.stderr)
        ls = listing(sess)
        print(("panes in %s:\n" % sess + "\n".join(ls)) if ls else "no deck session %s running" % sess,
              file=sys.stderr)
        return 2
    if "--once" in a or not sys.stdout.isatty():
        w, rows = shutil.get_terminal_size((80, 24))
        lines, pid = frame(sess, target, w, rows, True)
        print("\n".join(l.replace(INV, "").replace(RST, "") for l in lines))
        return 0 if pid else 1
    return watch(sess, target, "--view" in a)


if __name__ == "__main__":
    sys.exit(main() or 0)
