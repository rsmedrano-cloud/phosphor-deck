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

def _read_face(path, name):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        import dlog
        dlog.event("ADJUTANT", "face-load-failed", name)   # never the exception text: it quotes the full path
        return {}

def load_face(name):
    """A face made by `phosphor face`: a list of character frames."""
    return _read_face(os.path.join(FACES_DIR, name + ".json"), name).get("frames") or []

def load_bitmap(name=None):
    """A bitmap face (`phosphor face --bitmap`): NAME's, else the bundled one.
    None when it isn't one (or doesn't load): the character faces take over."""
    import facebmp
    path = os.path.join(FACES_DIR, name + ".json") if name else share("adjutant-face.json")
    bm = _read_face(path, name or "adjutant-face").get("bitmap")
    if not isinstance(bm, dict) or not bm.get("open"):
        return None
    try:
        return facebmp.Face(bm, PALETTES[THEME])
    except Exception:
        import dlog
        dlog.event("ADJUTANT", "face-load-failed", name or "adjutant-face")
        return None

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

def _read_fleet():
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
    return _fleet_cache["data"]

def fleet_alert():
    """Checked every tick of the main loop (every 20ms, tty_ok) -- a stat()
    call is cheap, re-opening and re-parsing fleet.json isn't, especially
    on a slow SD card (the "revived" shape's whole reason to exist). Only
    actually re-reads it when its mtime moves, which is once a poll round
    (~15s), not fifty times a second."""
    d = _read_fleet()
    if d is None:
        return None
    if time.time() - d.get("t", 0) > 120: return None
    for name, h in d.get("hosts", {}).items():
        if not h.get("ok"):
            return (2, "%s unreachable" % name)
        for _, pct, _ in h.get("mnt", []):
            if pct >= 92: return (2, "%s disk %d%%" % (name, pct))
    return None

def fleet_health():
    """(lvl, why).
    lvl: 0 nominal, 1 warning, 2 alert.
    why: text for idle display (e.g. "nominal", "web disk 88%", "stale data"), or "" if no fleet.
    """
    d = _read_fleet()
    if d is None:
        return 0, ""
    hosts = d.get("hosts", {})
    if not hosts:
        return 0, ""
    if time.time() - d.get("t", 0) > 120:
        return 1, "stale data"
    lvl, why = 0, "nominal"
    for name, h in hosts.items():
        if not h.get("ok"):
            return 2, "%s unreachable" % name
        for _, pct, _ in h.get("mnt", []):
            if pct >= 92:
                return 2, "%s disk %d%%" % (name, pct)
            elif pct >= 85 and lvl < 1:
                lvl, why = 1, "%s disk %d%%" % (name, pct)
    return lvl, why

def corrupt(line, amount):
    """Swap characters at random: the static."""
    if amount <= 0: return line
    out = list(line)
    for i in range(len(out)):
        if out[i] != " " and random.random() < amount:
            out[i] = random.choice(NOISE)
    return "".join(out)

def main():
    anim, tick, bmp = [], 0, None
    if "--face" in sys.argv:
        try: fname = sys.argv[sys.argv.index("--face") + 1]
        except IndexError: fname = None
        bmp = load_bitmap(fname) if fname else None
        if not bmp and fname: anim = load_face(fname)
    else:
        bmp = load_bitmap()                 # the bundled one
    speed = 4
    if "--speed" in sys.argv:
        try: speed = max(1, int(sys.argv[sys.argv.index("--speed") + 1]))
        except (IndexError, ValueError): pass

    cols, rows = shutil.get_terminal_size((34, 14))
    pos = os.path.getsize(EVENTS) if os.path.exists(EVENTS) else 0
    msg, lvl, burst, seen, target = "", 0, 0.0, None, ""
    from_fleet, msg_t = False, 0.0
    MSG_TTL = 120          # an old message doesn't stay forever
    t0 = t_frame = time.time()
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
    import relay
    pace = relay.Pace("ADJUTANT")       # a screen through a relay gets one frame a second
    try:
        while True:
            cols, rows = shutil.get_terminal_size((34, 14))
            # never wider than the pane: on a phone it can be a dozen columns
            w = max(3, min(cols, 100 if bmp else 40))

            new, pos = read_events(pos)
            if new:
                target, m = new[-1]
                msg, lvl, burst = m[:max(1, w-4)], 1, 1.0
                from_fleet, msg_t = False, time.time()
            else:
                al = fleet_alert()
                if al and al[1] != seen:
                    seen = al[1]; lvl, msg, burst = al[0], al[1][:max(1, w-4)], 1.0
                    target, from_fleet, msg_t = "SYS", True, time.time()
                elif not al:
                    # resolved: a fleet alert withdraws itself
                    if from_fleet and msg:
                        msg, lvl, target, from_fleet = "", 0, "", False
                    seen = None
            if msg and not from_fleet and time.time() - msg_t > MSG_TTL:
                msg, lvl, target = "", 0, ""

            # the glitch fades by the clock, not by frames: a slow pace keeps its length
            tnow = time.time()
            burst = max(0.0, burst - 0.055 * min(10.0, (tnow - t_frame) / 0.1))
            t_frame = tnow
            h_lvl, h_why = fleet_health()
            disp_lvl = max(lvl, h_lvl if not msg else 0)
            col  = (PH, AMB, RED)[min(disp_lvl, 2)]
            idle = burst <= 0 and not msg

            now = time.time() - t0
            if bmp:
                # the picture takes the whole pane: borders and the message line stay
                lines = bmp.draw(w - 2, max(2, rows - 3),
                                 "closed" if (now % 5.3) < 0.16 and burst <= 0 else "open",
                                 min(disp_lvl, 2), now, burst,
                                 sweep=(now * 0.22) % 1.6 if idle else None)
                out = [RULE + "╭" + "─" * (w - 2) + "╮" + RST]
                out += [RULE + "│" + RST + ln + RULE + "│" + RST for ln in lines]
            else:
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
                drift = int(now * 6) % (len(face) + 4) if face else 0
                for i, row_s in enumerate(face):
                    line = corrupt(row_s, burst * 0.55)[:max(0, w - 3)]
                    c = BLOOM if (i == drift and idle) else col     # a scanline sweeping by
                    out.append(RULE + "│" + RST + " " * (pad_l + 1) + c + line + RST
                               + " " * max(0, w - 2 - pad_l - 1 - len(line)) + RULE + "│" + RST)
                if rows > len(face) + 3:
                    out.append(RULE + "│" + RST + " " * (w - 2) + RULE + "│" + RST)

            if msg:
                shown = msg[:max(1, w - 2)]          # the pane may have shrunk since
                txt = corrupt(shown, burst * 0.8)
                pad_m = max(0, (w - 2 - len(shown)) // 2)
                out.append(RULE + "│" + RST + " " * pad_m + col + txt + RST
                           + " " * max(0, w - 2 - pad_m - len(shown)) + RULE + "│" + RST)
            else:
                if h_why:
                    idle_col = (DIM, AMB, RED)[min(h_lvl, 2)]
                    full = "· listening · %s ·" % h_why
                    short = "· %s ·" % h_why
                    room = max(1, w - 2)
                    if len(full) <= room:
                        idle_txt = full
                    elif len(short) <= room:
                        idle_txt = short
                    elif len("· listening ·") <= room:
                        idle_txt = "· listening ·"
                    else:
                        idle_txt = short[:room]
                else:
                    idle_col = DIM
                    idle_txt = "· listening ·"[:max(1, w - 2)]
                pad_m = max(0, (w - 2 - len(idle_txt)) // 2)
                out.append(RULE + "│" + RST + " " * pad_m + idle_col + idle_txt + RST
                           + " " * max(0, w - 2 - pad_m - len(idle_txt)) + RULE + "│" + RST)
            out.append(RULE + "╰" + "─" * (w - 2) + "╯" + RST)

            # Never more lines than rows: the terminal would scroll and the
            # pane would pile up scrollback forever.
            out = out[:max(1, rows)]
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            wait = pace.delay(0.08 if tty_ok else 0.1)
            if tty_ok and select.select([sys.stdin], [], [], wait)[0]:
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
                time.sleep(0.02 if tty_ok else wait)
    except KeyboardInterrupt:
        pass
    finally:
        if tty_ok:
            sys.stdout.write("\x1b[?1006l\x1b[?1000l")
            try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
            except Exception: pass
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
