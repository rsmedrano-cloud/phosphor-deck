#!/usr/bin/env python3
"""phosphor screens - who's attached to the deck, from the deck.

Every screen (phone, tablet, another computer) that ssh's in per phones.md
shows up here: where it's from, how long it's been idle, and a key to kick
it loose -- so a screen that's making a tab's pane small (zellij ties a
tab's whole grid to its smallest attached client, and there's no setting
to change that) doesn't need you to walk over to it and detach it by hand.

    phosphor screens           the panel: j/k move, x (twice) kicks, o (twice)
                               changes its kind's deck, r refreshes
    phosphor screens --list    the same, printed once, no picker

`o` on a screen in a deck of its own ([screens.KIND]) takes that block out
of the profile, so every screen of that kind shares the deck again; on a
screen that says a kind (`deck --screen phone`) and shares the deck, it
adds the block, so that kind gets a deck of its own. Either way the
screens of that kind are kicked and come back where they now belong, and
a kind's session nobody comes into anymore is closed.

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
import os, re, shutil, signal, subprocess, sys, time
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


def said(pid):
    """The kind the screen said it is when it came in (`deck --screen phone`,
    seen on its `phosphor attach`'s argv), '' if it said none."""
    import kinds
    for d in descendants(pid):
        try:
            parts = [p.decode("utf-8", "replace")
                     for p in open("/proc/%d/cmdline" % d, "rb").read().split(b"\0") if p]
        except OSError:
            continue
        if "attach" in parts and any(p == "--screen" or p.startswith("--screen=") for p in parts):
            return kinds.arg(parts)[0]
    return ""


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
                     "idle": "now" if idle in (".", "0") else idle, "pid": pid, "session": on,
                     "said": said(pid)})
    return rows


def _mine(pid):
    try:
        return os.stat("/proc/%d" % pid).st_uid == os.getuid()
    except OSError:
        return False


def targets(pid, mine=_mine):
    """What to signal to end the login `pid` stands for. `who -u` names sshd's
    privileged monitor, which runs as root: we can't signal it, and a kick
    that tried got "not allowed" on every ssh screen. Its child that runs as
    us (`sshd: you@pts/N`, or `sshd-session` on newer OpenSSH) is the
    connection's own end: ending it drops the link and the monitor follows.
    So: `pid` itself if it's ours (a local login), else the topmost
    descendants that are ours."""
    if mine(pid):
        return [pid]
    tree = descendants(pid)
    ours = set(p for p in tree[1:] if mine(p))
    parent = {}
    for p in ours:
        try:
            stat = open("/proc/%d/stat" % p).read()
            parent[p] = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            parent[p] = None
    return sorted(p for p in ours if parent[p] not in ours)


def kick(pid, mine=_mine):
    if not os.path.exists("/proc/%d" % pid):
        return False, "already gone"
    hit = targets(pid, mine)
    if not hit:
        return False, "not allowed to signal %d" % pid
    done = 0
    for p in hit:
        try:
            os.kill(p, signal.SIGTERM)
            done += 1
        except ProcessLookupError:
            done += 1
        except PermissionError:
            pass
    if not done:
        return False, "not allowed to signal %d" % pid
    return True, "kicked %d -- it should reconnect in a few seconds" % pid


def change(r, have, base):
    """What `o` does to screen r: ("share", kind) takes [screens.KIND] out,
    ("own", kind) adds it, (None, why) does nothing."""
    if r["session"] != base:
        return "share", r["session"][len(base) + 1:]
    k = r.get("said") or ""
    if not k:
        return None, "it says no kind: on it, phosphor screen --as KIND (or phone --as KIND)"
    if k in have:
        return None, "%s has a deck of its own now: x, and it goes there" % k
    import kinds
    if not kinds.NAME.match(k):
        # [screens.KIND] wants lowercase letters and digits: anything else
        # would be a block the deck ignores
        return None, "it says %r: a kind is lowercase letters and digits (phosphor screen --as KIND)" % k[:20]
    return "own", k


def moving(rows, action, kind, base):
    """The screens a change of `kind` sends somewhere else."""
    if action == "share":
        return [r for r in rows if r["session"] == "%s-%s" % (base, kind)]
    return [r for r in rows if r["session"] == base and r.get("said") == kind]


def _gen():
    phosphor = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "phosphor")
    return subprocess.run([sys.executable, phosphor, "gen"], capture_output=True).returncode == 0


def retype(action, kind, gen=_gen):
    """Write the change into the profile (a backup first) and gen, so a
    kind's new session has its layout. (ok, message)."""
    import deck_setup
    p = deckconf.path()
    if p == deckconf.EXAMPLE:
        return False, "no profile yet: phosphor init"
    try:
        text = open(p).read()
    except OSError as e:
        return False, "can't read the profile: %s" % e
    t2 = (deck_setup.add_screen_text(text, kind) if action == "own"
          else deck_setup.remove_screen_text(text, kind))
    err = deckconf.write_profile(
        t2, lambda prof: (kind in (prof.get("screens") or {})) == (action == "own"), expect=text, p=p)
    if err:
        return False, "not saved: " + (err if "didn't look right" not in err
                                        else "[screens.%s] isn't where it should be" % kind)
    if not gen():
        return False, "saved, but phosphor gen failed: phosphor gen shows why"
    return True, ""


def close_session(name):
    """A kind's session nobody comes into anymore: its panes go."""
    import kinds
    zj = deckconf.exe("zellij") or "zellij"
    kinds.forget(name)          # first: run from that session, this pane goes with it
    for a in ("kill-session", "delete-session"):
        subprocess.run([zj, a, name], capture_output=True, timeout=15)


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
        # a screen that says a kind with no deck of its own: deck (phone)
        if r["session"] != base:
            return r["session"][len(base) + 1:]
        return "deck (%s)" % r["said"] if r.get("said") else "deck"
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
            print("%-10s %-16s %-14s %-16s idle %-8s pid %d%s" %
                  (r["tty"], r["from"], kind(r), r["login"], r["idle"], r["pid"],
                   "  " + link(r) if link(r) else ""))
        return 0

    rows = screens(session)
    if rows is None:
        print(RED + "who isn't installed" + RST); return 1
    sel, confirm, msg = 0, None, ""
    oconfirm = None
    raw_screen(True)
    try:
        while True:
            cols, _ = shutil.get_terminal_size((90, 30))
            w = min(cols, 90)
            out = topbar("SCREENS", "who's attached", "%d · %s" % (len(rows), base), w)
            if not rows:
                out.append(" " + DIM + "no screens attached" + RST)
            for i, r in enumerate(rows):
                nm = "%-16s %-14s %-12s idle %-8s %s" % (r["from"], kind(r), r["tty"], r["idle"], link(r))
                line = " " + FG + nm + RST
                if confirm == i:
                    line = pad(line, w - 14) + AMB + "x again to kick" + RST
                if oconfirm == i:
                    line = pad(line, w - 14) + AMB + "o again" + RST
                if i == sel:
                    line = INV + pad(" " + nm, w - 4) + RST
                out.append(line)
            out.append("")
            if oconfirm is not None and oconfirm < len(rows):
                a, kd = change(rows[oconfirm], kinds.kinds(prof), base)
                if a == "own":
                    out.append(" " + AMB + "o again: %s gets a deck of its own, with every tab." % kd + RST)
                    out.append(" " + DIM + "Its panes, shells and assistants start a second time there"
                               " (phosphor mem shows the memory)." + RST)
                else:
                    out.append(" " + AMB + "o again: every %s shares this deck again;" % kd
                               + " %s-%s and its panes close." % (base, kd) + RST)
                out.append("")
            out.append(DIM + " j/k move · x kick (twice) · o own deck or share (twice) · r refresh · q quit" + RST)
            if msg:
                out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()

            k = ui_getkey(None)
            if k in ("q", "\x03"):
                break
            elif k in ("j", "\x1b[B"):
                sel = min(sel + 1, max(0, len(rows) - 1)); confirm, oconfirm, msg = None, None, ""
            elif k in ("k", "\x1b[A"):
                sel = max(sel - 1, 0); confirm, oconfirm, msg = None, None, ""
            elif k == "o" and rows:
                prof, _ = deckconf.load()
                a, kd = change(rows[sel], kinds.kinds(prof), base)
                if a is None:
                    msg, oconfirm = DIM + kd + RST, None
                elif oconfirm != sel:
                    oconfirm, confirm, msg = sel, None, ""
                else:
                    oconfirm = None
                    ok, m = retype(a, kd)
                    if ok:
                        gone = moving(rows, a, kd, base)
                        for r in gone:
                            kick(r["pid"])
                        if a == "share":
                            close_session("%s-%s" % (base, kd))
                        session = [base] + kinds.all_sessions(deckconf.load()[0])
                        m = ("%s gets a deck of its own" % kd if a == "own"
                             else "%s shares this deck again" % kd)
                        m += ("; %d screen%s reconnecting" % (len(gone), "" if len(gone) == 1 else "s")
                              if gone else "") + " · backup: deck.toml.bak"
                    msg = (PH + "✓ " if ok else RED + "✗ ") + m + RST
                    time.sleep(1)
                    rows = screens(session)
                    sel = min(sel, max(0, len(rows) - 1))
            elif k == "r":
                rows = screens(session)
                addrs = relay.relayed(relay.ts_status())
                sel = min(sel, max(0, len(rows) - 1))
                confirm, oconfirm, msg = None, None, PH + "refreshed" + RST
            elif k == "x" and rows:
                oconfirm = None
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
