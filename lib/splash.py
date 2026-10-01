"""A second of warm-up when a screen comes into the deck (issue #47).

An old CRT powering on: a dot, a line, the name glowing white-hot and
settling into the theme's color, one line of what you're walking into.
About a second, and any key skips it (that key is swallowed, never typed
into the deck). Nothing here reads the network: the line comes from the
profile alone, so a dead fleet never slows getting in.

Never shown: without a terminal, on the paper theme (e-ink ghosts every
frame), with `splash = false` in [deck], or when this same screen came in
less than a minute ago -- a phone's reconnect loop shouldn't replay it on
every dropped link.
"""
import hashlib, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf, ui

RECENT = 60      # seconds: the same screen coming back this soon skips it

GLYPHS = {       # three rows of half blocks per letter
    "P": ("█▀█", "█▀▀", "▀  "),
    "H": ("█ █", "█▀█", "▀ ▀"),
    "O": ("█▀█", "█ █", "▀▀▀"),
    "S": ("█▀▀", "▀▀█", "▀▀▀"),
    "R": ("█▀█", "█▀▄", "▀ ▀"),
}

def logo(word="PHOSPHOR"):
    return [" ".join(GLYPHS[c][r] for c in word) for r in range(3)]

def status(prof):
    deck = (prof or {}).get("deck") or {}
    try:
        ver = open(os.path.join(ui.REPO, "VERSION")).read().strip()
    except OSError:
        ver = ""
    hosts = [h for h in (prof or {}).get("hosts") or []
             if h.get("role") != "viewer" and h.get("fleet", True) is not False]
    bits = [deck.get("session", "deck")]
    if ver: bits.append("v" + ver)
    if len(hosts) > 1: bits.append("%d machines" % len(hosts))
    return " · ".join(bits)

def _marker():
    """One file per screen: ssh's client address, or this machine itself."""
    who = (os.environ.get("SSH_CONNECTION") or "local").split(" ")[0]
    return os.path.join(deckconf.cache_dir(), "splash",
                        hashlib.sha1(who.encode()).hexdigest()[:12])

def wanted(prof):
    deck = (prof or {}).get("deck") or {}
    if deck.get("splash", True) is False or ui.theme_name(prof) == "paper":
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if os.environ.get("TERM", "dumb") == "dumb":
        return False
    m = _marker()
    try:
        recent = time.time() - os.path.getmtime(m) < RECENT
    except OSError:
        recent = False
    try:                            # every attach counts, so a flapping link stays quiet
        os.makedirs(os.path.dirname(m), exist_ok=True)
        open(m, "w").close()
    except OSError:
        pass
    return not recent

def frames(cols, rows, prof):
    """(text, seconds to hold it) for each frame, already positioned."""
    cy, cx = rows // 2, cols // 2
    art = logo() if cols >= 36 else ["P H O S P H O R"]
    w = max(len(l) for l in art)
    top = max(1, cy - len(art) // 2)
    def at(y, x, s): return "\x1b[%d;%dH%s" % (y, max(1, x), s)
    def lines(color):
        return "".join(at(top + i, cx - w // 2 + 1, color + l + ui.RST) for i, l in enumerate(art))
    out = [(at(cy, cx, ui.BLOOM + "·" + ui.RST), 0.08)]
    span = min(cols - 2, w + 8)
    for k in (3, 6, 10, 14):                      # the beam opens out sideways
        n = max(1, span * k // 14)
        out.append(("\x1b[2J" + at(cy, cx - n // 2 + 1, ui.BLOOM + "─" * n + ui.RST), 0.04))
    out.append(("\x1b[2J" + lines(ui.BLOOM), 0.12))   # white-hot
    out.append((lines(ui.PH), 0.10))                  # settling into the phosphor
    line = status(prof)
    out.append((at(top + len(art) + 1, cx - len(line) // 2 + 1, ui.DIM + line + ui.RST), 0.55))
    return out

def show(prof):
    """The warm-up, if this attach wants one. Returns quickly either way."""
    if not wanted(prof):
        return
    cols, rows = shutil.get_terminal_size((80, 24))
    w = sys.stdout.write
    w("\x1b[?1049h\x1b[?25l\x1b[2J"); sys.stdout.flush()
    try:
        for text, hold in frames(cols, rows, prof):
            w(text); sys.stdout.flush()
            if ui.getkey(timeout=hold) is not None:
                break                               # any key: straight in
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        w("\x1b[2J\x1b[?25h\x1b[?1049l"); sys.stdout.flush()
