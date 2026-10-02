#!/usr/bin/env python3
"""phosphor screens - who's attached to the deck, from the deck.

Every screen (phone, tablet, another computer) that ssh's in per phones.md
shows up here: where it's from, how long it's been idle, and a key to kick
it loose -- so a screen that's making a tab's pane small (zellij ties a
tab's whole grid to its smallest attached client, and there's no setting
to change that) doesn't need you to walk over to it and detach it by hand.

    phosphor screens           the panel: j/k move, x (twice) kicks, r refreshes
    phosphor screens --list    the same, printed once, no picker

A kick ends that one ssh connection; its own `deck` wrapper (phones.md)
notices the drop and reconnects within a few seconds on its own -- this
forces one reconnect, it never bans a device. Only sessions actually
running `zellij attach <session>` show up: an unrelated ssh login to the
same machine is left alone. There's no reliable way to tell which of them
is the screen you're reading this from (a pane belongs to the session, not
to whichever client happens to be looking at it), so `x` needs a second
press on purpose -- kicking your own screen by mistake just costs you the
same few-second reconnect as any other.
"""
import os, re, shutil, signal, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, AMB, RED, RULE, RST, getkey as ui_getkey, pad, vlen, topbar, HEAD
import deckconf

INV = "\x1b[7m"

WHO_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(\S+)\s+(\d+)\s*(?:\(([^)]*)\))?\s*$")


def descendants(pid):
    """Every pid below `pid`, self included -- one /proc walk, no ps/pstree."""
    by_parent = {}
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            stat = open("/proc/%s/stat" % p).read()
        except OSError:
            continue
        try:
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (ValueError, IndexError):
            continue
        by_parent.setdefault(ppid, []).append(int(p))
    out, frontier = [pid], [pid]
    while frontier:
        nxt = []
        for x in frontier:
            for c in by_parent.get(x, []):
                out.append(c)
                nxt.append(c)
        frontier = nxt
    return out


def is_deck_client(pid, session):
    """The session `pid` (an sshd login) is attached to, if it has a `zellij
    ... attach <session>` descendant -- the phone/screen kit's `deck` wrapper
    always execs one -- else None. `session` can be a list of them."""
    want = [session] if isinstance(session, str) else list(session)
    for d in descendants(pid):
        try:
            cmdline = open("/proc/%d/cmdline" % d, "rb").read()
        except OSError:
            continue
        parts = [p.decode("utf-8", "replace") for p in cmdline.split(b"\0") if p]
        if parts and os.path.basename(parts[0]) == "zellij" and "attach" in parts:
            hit = next((s for s in want if s in parts), None)
            if hit:
                return hit
    return None


def screens(session):
    """Every attached screen, as {tty, from, login, idle, pid, session}. None if
    `who` isn't installed (rare, but not every image has util-linux)."""
    who = deckconf.exe("who")
    if not who:
        return None
    try:
        out = subprocess.run([who, "-u"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        m = WHO_RE.match(line)
        if not m:
            continue
        _, tty, date, time_, idle, pid, frm = m.groups()
        pid = int(pid)
        on = is_deck_client(pid, session)
        if not on:
            continue
        rows.append({"tty": tty, "from": frm or "local", "login": "%s %s" % (date, time_),
                     "idle": "now" if idle in (".", "0") else idle, "pid": pid, "session": on})
    return rows


def kick(pid):
    try:
        os.kill(pid, signal.SIGTERM)
        return True, "kicked %d -- it should reconnect in a few seconds" % pid
    except ProcessLookupError:
        return False, "already gone"
    except PermissionError:
        return False, "not allowed to signal %d" % pid


def raw_screen(on):
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h" if on
                      else "\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")
    sys.stdout.flush()


def main():
    prof, _ = deckconf.load()
    import kinds
    base = ((prof or {}).get("deck") or {}).get("session", "deck")
    # the deck's own session and every kind of screen's (deck-phone...)
    session = [base] + kinds.all_sessions(prof)
    def kind(r):
        return "deck" if r["session"] == base else r["session"][len(base) + 1:]
    import relay
    addrs = relay.relayed(relay.ts_status())
    def link(r):
        # through a tailscale relay: its deck's animations slow down for it
        return "relay" if relay.is_relayed(r["from"], addrs) else ""

    if "--list" in sys.argv[1:] or not sys.stdin.isatty():
        rows = screens(session)
        if rows is None:
            print("who isn't installed"); return 1
        if not rows:
            print("no screens attached"); return 0
        for r in rows:
            print("%-10s %-16s %-8s %-16s idle %-8s pid %d%s" %
                  (r["tty"], r["from"], kind(r), r["login"], r["idle"], r["pid"],
                   "  " + link(r) if link(r) else ""))
        return 0

    rows = screens(session)
    if rows is None:
        print(RED + "who isn't installed" + RST); return 1
    sel, confirm, msg = 0, None, ""
    raw_screen(True)
    try:
        while True:
            cols, _ = shutil.get_terminal_size((90, 30))
            w = min(cols, 90)
            out = topbar("SCREENS", "who's attached", "%d · %s" % (len(rows), base), w)
            if not rows:
                out.append(" " + DIM + "no screens attached" + RST)
            for i, r in enumerate(rows):
                nm = "%-16s %-8s %-12s idle %-8s %s" % (r["from"], kind(r), r["tty"], r["idle"], link(r))
                line = " " + FG + nm + RST
                if confirm == i:
                    line = pad(line, w - 14) + AMB + "x again to kick" + RST
                if i == sel:
                    line = INV + pad(" " + nm, w - 4) + RST
                out.append(line)
            out.append("")
            out.append(DIM + " j/k move · x kick (twice) · r refresh · q quit" + RST)
            if msg:
                out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()

            k = ui_getkey(None)
            if k in ("q", "\x03"):
                break
            elif k in ("j", "\x1b[B"):
                sel = min(sel + 1, max(0, len(rows) - 1)); confirm, msg = None, ""
            elif k in ("k", "\x1b[A"):
                sel = max(sel - 1, 0); confirm, msg = None, ""
            elif k == "r":
                rows = screens(session)
                addrs = relay.relayed(relay.ts_status())
                sel = min(sel, max(0, len(rows) - 1))
                confirm, msg = None, PH + "refreshed" + RST
            elif k == "x" and rows:
                if confirm == sel:
                    ok, m = kick(rows[sel]["pid"])
                    msg = (PH + "✓ " if ok else RED + "✗ ") + m + RST
                    confirm = None
                    rows = screens(session)
                    sel = min(sel, max(0, len(rows) - 1))
                else:
                    confirm, msg = sel, ""
    except KeyboardInterrupt:
        pass
    finally:
        raw_screen(False)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
