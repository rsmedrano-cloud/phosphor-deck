#!/usr/bin/env python3
"""phosphor keys - the key guide. Shows a section for every installed tool
(share/keys.json) and picks up new installs by itself."""
import json, os, select, shutil, subprocess, sys, termios, time, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, BLOOM, AMB, RULE, RST, REPO, share, vlen, pad
from ui import getkey as ui_getkey

HOME = os.path.expanduser("~")
BIN  = os.path.join(HOME, ".local/bin")
DB   = None  # resolved in main()
RESCAN = 5

def have(name):
    p = os.path.join(BIN, name)
    if os.path.isfile(p) and os.access(p, os.X_OK): return True
    return shutil.which(name) is not None

def build(db, w):
    kw = min(20, max(12, w // 3))
    lines, n = [], 0
    for key, sec in db.items():
        if not sec.get("always") and not have(key): continue
        n += 1
        lines.append("")
        title = " " + BLOOM + sec["t"] + RST
        lines.append(title + " " + RULE + "─"*max(0, w - vlen(title) - 2) + RST)
        for k, act in sec["k"]:
            if not k:
                lines.append("   " + DIM + act + RST)
            else:
                lines.append("   " + AMB + ("%-*s" % (kw, k)) + RST + FG + act + RST)
    return lines, n

def getkey(timeout):
    """A key, or 'WUP'/'WDN' for the wheel / two-finger scroll."""
    k = ui_getkey(timeout)
    if isinstance(k, tuple):
        return {64: "WUP", 65: "WDN"}.get(k[1]) if k[4] else None
    return k

def run_setup():
    """s runs setup in this same pane (no new tab, no floating pane) and the
    guide comes back when it exits. The DECK panel next to it has the rest."""
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    try:
        subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "setup"])
    except KeyboardInterrupt:
        pass
    sys.stdout.write("\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()

def mine(db):
    """The deck's own keys as [keys] in the profile has them."""
    if "_deck" in db:
        import deckconf, shortcuts
        db["_deck"]["k"] = shortcuts.guide_rows(db["_deck"]["k"], deckconf.load()[0])
    return db

def dump():
    """No TTY (a pipe, |less, a script): plain dump and exit."""
    try: db = mine(json.load(open(DB)))
    except Exception:
        import dlog
        dlog.event("KEYS", "load-failed")   # never str(e): it can quote the install path
        db = {}
    lines, n = build(db, 78)
    print("\n".join(lines))
    print()

def main():
    global DB
    DB = share("keys.json")

    if not sys.stdin.isatty():
        dump(); return
    off, last, db = 0, 0, {}
    lines, n = [], 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 30))
            w = min(cols, 100)
            if time.time() - last > RESCAN:
                try: db = mine(json.load(open(DB)))
                except Exception:
                    import dlog
                    dlog.event_throttled("KEYS", "load-failed")
                    db = {}
                lines, n = build(db, w); last = time.time()
            body = max(3, rows - 3)
            maxoff = max(0, len(lines) - body)
            off = max(0, min(off, maxoff))
            head = "─ KEYS "
            tail = "─ %d tools ─" % n
            out = [RULE + "╭" + head + "─"*max(0, w-2-len(head)-len(tail)) + tail + "╮" + RST]
            win = lines[off:off+body]
            for l in win: out.append(RULE+"│"+RST + pad(l, w-2) + RULE+"│"+RST)
            for _ in range(body - len(win)): out.append(RULE+"│"+RST + " "*(w-2) + RULE+"│"+RST)
            bar = "─ %d/%d ─" % (min(off+body, len(lines)), len(lines)) if maxoff else "──"
            out.append(RULE + "╰" + "─"*max(0, w-2-len(bar)) + bar + "╯" + RST)
            out.append(DIM + " j/k or two fingers: scroll · " + RST + AMB + "s" + RST
                       + DIM + " setup: machines and color" + RST)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"); sys.stdout.flush()

            k = getkey(1.0)
            if k is None: continue
            if k in ("q", "\x03"): break
            elif k in ("j", "\x1b[B", "WDN"): off += 3 if k == "WDN" else 1
            elif k in ("k", "\x1b[A", "WUP"): off -= 3 if k == "WUP" else 1
            elif k == " ": off += body
            elif k == "g": off = 0
            elif k == "G": off = maxoff
            elif k == "r": last = 0
            elif k == "s": run_setup(); last = 0
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n")

if __name__ == "__main__":
    main()
