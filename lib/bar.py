"""phosphor bar - one row at the bottom of every tab.

     ⌂ HOME Alt-1   ? ASK Alt-q   ✎ NOTE Alt-j   ⇲ EDIT Alt-r   ⤢ ZOOM Alt-z      ● 2

gen puts it in every tab's template when [bar] enabled = true. A tap on a
key does what its Alt key does, on the pane you were in: zellij gives the
tapped bar the focus (and sends it only the release), so the bar gives it
back (focus-last-pane) and then acts. With the focus (Alt-Down into it)
Left/Right pick a key, Enter runs it, Esc gives the focus back. A zoomed
pane covers the whole tab, the bar too: Alt-z (ZOOM on a phone's extra
keys, which keep it for that) gives the tab back.

Where there's room each key shows its shortcut; on a narrow screen (a
phone) only the word. The light on the right is glance's (green, amber,
red; dim with no fleet data) with the count of fleet problems; a tap opens
glance in place of the pane. One bar works it out for all of them: the
first to find the shared answer stale asks glance, in the background.

A tab whose last pane closed keeps only its bar (zellij doesn't close it,
nor resize the bar: it only focuses it), so on focus the bar looks, and
closes its tab when it's alone.

    phosphor bar                     what a tab's template runs
    phosphor bar --once [--width N]  one frame, printed
"""
import json, os, select, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, PH, AMB, RED, RST, REPO
import deckconf

NAME = "BAR"              # the pane's name in every layout: how the rest of phosphor skips it
PHOSPHOR = os.path.join(REPO, "phosphor")
LIB = os.path.dirname(os.path.abspath(__file__))
STALE = 30                # seconds before the light is asked again
LOCK_STALE = 60           # a lock older than this was left by a bar that died
# (id, glyph, word); the shortcut comes from [keys]. MIC joins with #85.
KEYS = [("home", "⌂", "HOME"), ("ask", "?", "ASK"), ("note", "✎", "NOTE"),
        ("edit", "⇲", "EDIT"), ("zoom", "⤢", "ZOOM")]
LIGHT = {"green": PH, "amber": AMB, "red": RED}
# what each pane-bound key opens in place of the pane: (name, phosphor args)
IN_PLACE = {"ask": ("ASK", ["ask", "--here"]), "note": ("NOTE", ["note", "--here"]),
            "edit": ("EDIT", ["edit"]), "light": ("GLANCE", ["glance"])}


def is_bar(p):
    """A list-panes entry (or a dumped layout pane's attrs) that is a bar."""
    if p.get("name") == NAME or p.get("title") == NAME:
        return True
    cmd = (p.get("terminal_command") or "").split()
    return len(cmd) >= 2 and os.path.basename(cmd[-2]) == "phosphor" and cmd[-1] == "bar"


def enabled(prof):
    return ((prof or {}).get("bar") or {}).get("enabled") is True


# ── what it shows ─────────────────────────────────────────────
def shortcuts_of(prof):
    """{key id: "Alt-q"} for the keys that have one."""
    import shortcuts
    k = shortcuts.current(prof)
    out = {i: shortcuts.dash(k[i]) for i, _, _ in KEYS if k.get(i)}
    if k["tabs"]:
        out["home"] = shortcuts.dash(k["tabs"] + " 1")   # until HOME is its own place
    return out


def light_text(status):
    """("● 2", color) for the right end; status is the shared answer or None."""
    st = (status or {}).get("status", "unknown")
    n = (status or {}).get("problems", 0)
    return ("● %d" % n) if n else "●", LIGHT.get(st, DIM)


# (key text, gap between keys): the richest that fits wins
def _tiers(keys):
    full = lambda i, g, w: "%s %s %s" % (g, w, keys[i]) if keys.get(i) else "%s %s" % (g, w)
    return [(full, 3), (lambda i, g, w: "%s %s" % (g, w), 3), (lambda i, g, w: "%s %s" % (g, w), 2),
            (lambda i, g, w: w, 2), (lambda i, g, w: w, 1)]


def layout(width, keys, light):
    """[(start, end, id, text)] across one row of `width` columns, 0-based,
    end exclusive: the keys from the left, the light at the right end.
    keys: {id: shortcut}; light: its text. A tap anywhere between two keys
    goes to the nearer one (hit())."""
    for fmt, gap in _tiers(keys):
        texts = [(i, fmt(i, g, w)) for i, g, w in KEYS]
        need = 1 + sum(len(t) for _, t in texts) + gap * (len(texts) - 1) + 2 + len(light) + 1
        if need <= width:
            break
    out, x = [], 1
    for i, t in texts:
        out.append((x, x + len(t), i, t))
        x += len(t) + gap
    lx = max(x - gap + 2, width - 1 - len(light))
    out.append((lx, lx + len(light), "light", light))
    return out


def hit(spans, col):
    """The id at this 0-based column: the key under it, else the nearest one."""
    if not spans:
        return None
    for a, b, i, _ in spans:
        if a <= col < b:
            return i
    return min(spans, key=lambda s: min(abs(col - s[0]), abs(col - (s[1] - 1))))[2]


def draw(width, keys, status, sel=None):
    """The row, painted: words in ink, shortcuts dim, the light in its color,
    the selected key (when the bar has the focus) in reverse."""
    text, color = light_text(status)
    spans = layout(width, keys, text)
    row, x = "", 0
    for a, b, i, t in spans:
        row += " " * (a - x)
        if i == "light":
            piece = color + t + RST
        else:
            short = keys.get(i, "")
            words = t[:len(t) - len(short)].rstrip() if short and t.endswith(short) else t
            piece = FG + words + RST + ((" " + DIM + short + RST) if words != t else "")
        row += ("\x1b[7m" + piece.replace(RST, RST + "\x1b[7m") + RST) if i == sel else piece
        x = b
    return spans, row


# ── the light, shared by every bar ────────────────────────────
def status_path():
    return os.path.join(deckconf.cache_dir(), "bar-status.json")


def read_status():
    try:
        with open(status_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def ask_glance():
    """A child working out glance's answer, or None when another bar is on
    it. The lock says who: made with O_EXCL, taken over when it's stale."""
    lock = status_path() + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) < LOCK_STALE:
                    return None
                os.remove(lock)
            except OSError:
                return None
    else:
        return None
    code = ("import sys, json; sys.path.insert(0, %r); import glance; p = glance.payload(); "
            "print(json.dumps({'status': p['status'], 'problems': len(p['fleet']['problems'])}))" % LIB)
    try:
        return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except OSError:
        os.remove(lock)
        return None


def took(child):
    """The child's answer into the shared file (when it ended); the lock goes."""
    try:
        out = child.stdout.read()
        child.wait()
        d = json.loads(out)
        d["t"] = time.time()
        tmp = status_path() + ".%d" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, status_path())
    except (OSError, ValueError, TypeError):
        pass
    finally:
        try: os.remove(status_path() + ".lock")
        except OSError: pass


# ── zellij ────────────────────────────────────────────────────
def zj(*a):
    import proc
    z = proc.zellij() or "zellij"
    try:
        return subprocess.run([z, "action"] + list(a), capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def panes():
    try:
        return json.loads(zj("list-panes", "-a", "-j") or "[]")
    except ValueError:
        return []


def me():
    try:
        return int(os.environ.get("ZELLIJ_PANE_ID", ""))
    except ValueError:
        return None


def my_tab(ps):
    mine = next((p for p in ps if not p.get("is_plugin") and p.get("id") == me()), None)
    return mine.get("tab_id") if mine else None


def alone():
    """My tab's id when nothing but bars is left in it, else None."""
    ps = panes()
    tab = my_tab(ps)
    if tab is None:
        return None
    rest = [p for p in ps if p.get("tab_id") == tab and not p.get("is_plugin") and not is_bar(p)]
    return None if rest else tab


def target():
    """The pane the key acts on: the focused one of my tab, once the focus is back."""
    ps = panes()
    tab = my_tab(ps)
    p = next((p for p in ps if p.get("tab_id") == tab and p.get("is_focused") and not p.get("is_plugin")
              and not p.get("is_floating") and not is_bar(p)), None)
    return "terminal_%d" % p["id"] if p else None


def act(key):
    """What the key's Alt shortcut does, on the pane you were in."""
    import dlog
    dlog.event("BAR", key)
    zj("focus-last-pane")
    if key == "home":
        zj("go-to-tab", "1")
        return
    pane = target()
    if not pane:
        return
    if key == "zoom":
        zj("toggle-fullscreen", "--pane-id", pane)
        return
    if key == "ask":
        import shortcuts
        zj("dump-screen", "--pane-id", pane, "--path", shortcuts.screen_dump())
    name, args = IN_PLACE[key]
    zj("new-pane", "--in-place", "--pane-id", pane, "--close-on-exit", "--name", name,
       "--", PHOSPHOR, *args)


# ── the loop ──────────────────────────────────────────────────
def events(buf):
    """(events, rest): ("tap", col), ("focus", bool), ("key", name) from
    the bytes read so far; rest is an unfinished sequence."""
    out = []
    while buf:
        if buf.startswith(b"\x1b[<"):
            end = next((i for i, c in enumerate(buf) if c in b"Mm" and i > 2), -1)
            if end < 0:
                return out, buf
            try:
                b, x, _ = (int(v) for v in buf[3:end].split(b";"))
                if buf[end:end + 1] == b"m" and b == 0:
                    out.append(("tap", x - 1))
            except ValueError:
                pass
            buf = buf[end + 1:]
        elif buf.startswith((b"\x1b[I", b"\x1b[O")):
            out.append(("focus", buf[2:3] == b"I")); buf = buf[3:]
        elif buf.startswith((b"\x1b[C", b"\x1bOC")):
            out.append(("key", "right")); buf = buf[3:]
        elif buf.startswith((b"\x1b[D", b"\x1bOD")):
            out.append(("key", "left")); buf = buf[3:]
        elif buf.startswith(b"\x1b[") or buf.startswith(b"\x1bO"):
            i = next((i for i, c in enumerate(buf[2:], 2) if 0x40 <= c <= 0x7e), -1)
            if i < 0:
                return out, buf
            buf = buf[i + 1:]                  # a key the bar has no use for
        elif buf == b"\x1b":
            return out, buf                    # Esc, or the start of something: the caller waits
        elif buf[:1] in (b"\r", b"\n"):
            out.append(("key", "enter")); buf = buf[1:]
        elif buf[:1] == b"\x1b":
            out.append(("key", "esc")); buf = buf[1:]
        else:
            out.append(("key", buf[:1].decode("latin-1"))); buf = buf[1:]
    return out, buf


def width():
    try:
        return os.get_terminal_size(1).columns
    except OSError:
        return 80


def run():
    import termios, tty
    prof, _ = deckconf.load()
    keys = shortcuts_of(prof)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setraw(fd)
    resized = [True]
    signal.signal(signal.SIGWINCH, lambda *a: resized.__setitem__(0, True))
    out = sys.stdout
    out.write("\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[?1004h")
    started, focused, sel, buf, shown = time.time(), False, 0, b"", None
    child, status, seen = None, read_status(), 0
    spans = []
    try:
        while True:
            if child is not None and child.poll() is not None:
                took(child); child = None
            try:
                m = os.path.getmtime(status_path())
            except OSError:
                m = 0
            if m != seen:
                seen, status = m, read_status()
            if child is None and time.time() - (status or {}).get("t", 0) > STALE:
                child = ask_glance()
            frame = (width(), json.dumps(status, sort_keys=True), focused and KEYS[sel][0])
            if frame != shown or resized[0]:
                resized[0] = False
                spans, row = draw(frame[0], keys, status, frame[2] or None)
                out.write("\x1b[H\x1b[2K" + row); out.flush()
                shown = frame
            try:
                ready = select.select([fd], [], [], 2.0)[0]
            except InterruptedError:
                continue
            if not ready:
                continue
            data = os.read(fd, 1024)
            if not data:
                return 0
            buf += data
            if buf == b"\x1b" and select.select([fd], [], [], 0.05)[0]:
                continue                       # more on its way: a sequence
            evs, buf = events(buf)
            if buf == b"\x1b":
                evs.append(("key", "esc")); buf = b""
            for kind, v in evs:
                if kind == "focus":
                    focused = v
                    # nothing left but me: the tab goes (a moment's grace at start)
                    if v and time.time() - started > 2:
                        tab = alone()
                        if tab is not None:
                            zj("close-tab-by-id", str(tab))
                elif kind == "tap":
                    focused = False
                    key = hit(spans, v)
                    if key:
                        act(key)
                elif v in ("left", "right"):
                    sel = (sel + (1 if v == "right" else -1)) % len(KEYS)
                elif v == "enter":
                    focused = False
                    act(KEYS[sel][0])
                elif v in ("esc", "q"):
                    focused = False
                    zj("focus-last-pane")
    finally:
        out.write("\x1b[?1004l\x1b[?1006l\x1b[?1000l\x1b[?25h"); out.flush()
        termios.tcsetattr(fd, termios.TCSAFLUSH, saved)
        if child is not None:
            took(child)


def main():
    args = sys.argv[1:]
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__.strip()); return 0
    if "--once" in args:
        prof, _ = deckconf.load()
        w = int(args[args.index("--width") + 1]) if "--width" in args else width()
        print(draw(w, shortcuts_of(prof), read_status())[1])
        return 0
    if not sys.stdin.isatty():
        print("phosphor bar: the row at the bottom of each tab; [bar] enabled = true and phosphor gen put it there",
              file=sys.stderr)
        return 2
    return run() or 0


if __name__ == "__main__":
    sys.exit(main() or 0)
