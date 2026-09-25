"""phosphor adjutant - the face that announces what happens.

It idles quietly. On an event the image breaks up into decaying static and
the message is left behind it (a nod to StarCraft's Adjutant).

Event sources:
  · ~/.cache/phosphor/events       anyone appends a line (phosphor notify)
  · ~/.cache/phosphor/fleet.json   fleet alerts: host down, disk full
"""
import json, os, random, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

HOME   = os.path.expanduser("~")
CACHE  = deckconf.cache_dir()
EVENTS = os.path.join(CACHE, "events")
FLEET  = os.path.join(CACHE, "fleet.json")
FACES_DIR = os.path.join(deckconf.data_dir(), "faces")

NOISE = "▒▓█░▚▞▙▟▛▜▗▖▘▝╳╱╲┃━"

def load_face(name):
    """A face made by `phosphor face`: a list of frames."""
    try:
        with open(os.path.join(FACES_DIR, name + ".json")) as f:
            d = json.load(f)
        return d.get("frames") or []
    except Exception:
        import dlog
        dlog.event("ADJUTANT", "face-load-failed", name)   # never the exception text: it quotes the full path
        return []

# Fallback when there's no face file: a helmet with a visor.
FACE = [
    "  ▄▄▄▄▄▄▄▄▄  ",
    " █░░░░░░░░░█ ",
    "█░▟▀▀▀▀▀▀▀▙░█",
    "█░█ ●   ● █░█",
    "█░▜▄▄▄▄▄▄▄▟░█",
    " █░░▄▄▄▄▄░░█ ",
    "  ▀▀▀▀▀▀▀▀▀  ",
]

def zj(*args):
    """Talk to zellij, quietly: the adjutant must never die because of it."""
    import shutil as _sh, subprocess as _sp
    b = os.path.expanduser("~/.local/bin/zellij")
    if not os.path.exists(b): b = _sh.which("zellij")
    if not b: return
    try:
        _sp.run([b, "-s", os.environ.get("ZELLIJ_SESSION_NAME", "deck"),
                 "action"] + list(args), capture_output=True, timeout=8)
    except Exception:
        import dlog
        # never str(e): it quotes the full command, home path included
        dlog.event_throttled("ADJUTANT", "zj-failed")

def read_events(pos):
    """New lines since the last read."""
    out = []
    try:
        sz = os.path.getsize(EVENTS)
        if sz < pos: pos = 0          # the file was truncated
        if sz > pos:
            with open(EVENTS) as f:
                f.seek(pos)
                out = []
                for l in f.read().splitlines():
                    if not l.strip(): continue
                    tab, _, m = l.partition("\t")
                    out.append((tab.strip(), (m or tab).strip()))
                pos = f.tell()
    except FileNotFoundError:
        pos = 0
    return out, pos

_fleet_cache = {"mtime": None, "data": None}

def fleet_alert():
    """Checked every tick of the main loop (every 20ms, tty_ok) -- a stat()
    call is cheap, re-opening and re-parsing fleet.json isn't, especially
    on a slow SD card (the "revived" shape's whole reason to exist). Only
    actually re-reads it when its mtime moves, which is once a poll round
    (~15s), not fifty times a second."""
    try:
        mtime = os.path.getmtime(FLEET)
    except OSError:
        return None
    if mtime != _fleet_cache["mtime"]:
        try:
            with open(FLEET) as f:
                _fleet_cache["data"] = json.load(f)
            _fleet_cache["mtime"] = mtime
        except Exception:
            import dlog
            dlog.event_throttled("ADJUTANT", "fleet-json-failed")
            return None
    d = _fleet_cache["data"]
    if d is None:
        return None
    if time.time() - d.get("t", 0) > 120: return None
    for name, h in d.get("hosts", {}).items():
        if not h.get("ok"):
            return (2, "%s unreachable" % name)
        for _, pct, _ in h.get("mnt", []):
            if pct >= 92: return (2, "%s disk %d%%" % (name, pct))
    return None

def corrupt(line, amount):
    """Swap characters at random: the static."""
    if amount <= 0: return line
    out = list(line)
    for i in range(len(out)):
        if out[i] != " " and random.random() < amount:
            out[i] = random.choice(NOISE)
    return "".join(out)

def main():
    anim, tick = [], 0
    if "--face" in sys.argv:
        try: anim = load_face(sys.argv[sys.argv.index("--face") + 1])
        except IndexError: anim = []
    speed = 4
    if "--speed" in sys.argv:
        try: speed = max(1, int(sys.argv[sys.argv.index("--speed") + 1]))
        except (IndexError, ValueError): pass

    cols, rows = shutil.get_terminal_size((34, 14))
    pos = os.path.getsize(EVENTS) if os.path.exists(EVENTS) else 0
    msg, lvl, burst, seen, target = "", 0, 0.0, None, ""
    from_fleet, msg_t = False, 0.0
    MSG_TTL = 120          # an old message doesn't stay forever
    t0 = time.time()
    import select, termios, tty
    # Only the floating one (--floating) reads keys and talks to zellij. The
    # SYS one is display only: a key pressed there can't trigger anything.
    tty_ok = sys.stdin.isatty() and "--floating" in sys.argv
    old = None
    if tty_ok:
        try:
            old = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write("\x1b[?1000h\x1b[?1006h")   # clicks
        except Exception as e:
            import dlog
            dlog.event("ADJUTANT", "tty-setup-failed", str(e)[:60])
            tty_ok = False
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((34, 14))
            w = max(20, min(cols, 40))

            new, pos = read_events(pos)
            if new:
                target, m = new[-1]
                msg, lvl, burst = m[:w-4], 1, 1.0
                from_fleet, msg_t = False, time.time()
            else:
                al = fleet_alert()
                if al and al[1] != seen:
                    seen = al[1]; lvl, msg, burst = al[0], al[1][:w-4], 1.0
                    target, from_fleet, msg_t = "SYS", True, time.time()
                elif not al:
                    # resolved: a fleet alert withdraws itself
                    if from_fleet and msg:
                        msg, lvl, target, from_fleet = "", 0, "", False
                    seen = None
            if msg and not from_fleet and time.time() - msg_t > MSG_TTL:
                msg, lvl, target = "", 0, ""

            burst = max(0.0, burst - 0.055)
            col  = (PH, AMB, RED)[min(lvl, 2)]
            idle = burst <= 0 and not msg

            face_room = max(0, rows - 4)       # minus borders, gap and message
            if anim:
                tick += 1
                cur = anim[(tick // speed) % len(anim)]
            else:
                cur = FACE
            face = cur if face_room >= len(cur) else cur[:face_room]
            out = [RULE + "╭" + "─" * (w - 2) + "╮" + RST]
            fw = max((len(r) for r in face), default=13)
            pad_l = max(0, (w - 2 - fw) // 2)
            drift = int((time.time() - t0) * 6) % (len(face) + 4) if face else 0
            for i, row_s in enumerate(face):
                line = corrupt(row_s, burst * 0.55)
                c = BLOOM if (i == drift and idle) else col     # a scanline sweeping by
                out.append(RULE + "│" + RST + " " * (pad_l + 1) + c + line + RST
                           + " " * max(0, w - 2 - pad_l - 1 - len(line)) + RULE + "│" + RST)
            if rows > len(face) + 3:
                out.append(RULE + "│" + RST + " " * (w - 2) + RULE + "│" + RST)

            if msg:
                txt = corrupt(msg, burst * 0.8)
                pad_m = max(0, (w - 2 - len(msg)) // 2)
                out.append(RULE + "│" + RST + " " * pad_m + col + txt + RST
                           + " " * max(0, w - 2 - pad_m - len(msg)) + RULE + "│" + RST)
            else:
                idle_txt = "· listening ·"
                pad_m = max(0, (w - 2 - len(idle_txt)) // 2)
                out.append(RULE + "│" + RST + " " * pad_m + DIM + idle_txt + RST
                           + " " * max(0, w - 2 - pad_m - len(idle_txt)) + RULE + "│" + RST)
            out.append(RULE + "╰" + "─" * (w - 2) + "╯" + RST)

            # Never more lines than rows: the terminal would scroll and the
            # pane would pile up scrollback forever.
            out = out[:max(1, rows)]
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            if tty_ok and select.select([sys.stdin], [], [], 0.08)[0]:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = ""
                    while select.select([sys.stdin], [], [], 0.02)[0]:
                        c = sys.stdin.read(1); seq += c
                        if c in "Mm~": break
                    if seq.startswith("[<") and seq.endswith("M"):
                        btn = int(seq[2:].split(";")[0])
                        if btn == 0:           # click: take me where I should look
                            if target: zj("go-to-tab-name", target)
                            zj("hide-floating-panes")
                            msg, target, burst = "", "", 0.0
                    else:
                        zj("hide-floating-panes")
                else:
                    # Any key closes it. This pane takes focus when it shows
                    # up, and if it swallowed the keyboard the deck would be
                    # unusable (it happened).
                    zj("hide-floating-panes")
                    msg, target, burst = "", "", 0.0
            else:
                time.sleep(0.02 if tty_ok else 0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if tty_ok:
            sys.stdout.write("\x1b[?1006l\x1b[?1000l")
            try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
            except Exception: pass
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
