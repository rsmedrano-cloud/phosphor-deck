"""phosphor panel - the DECK tab: the deck's own state, what's left to set
up, and every phosphor action one key (or one tap) away, each one a card
(lib/card.py): its live value, and the command that does it in a terminal.

It runs on the brain, so phosphor always has a place to run even when every
other tab is an ssh to somewhere else. Actions run in this same pane and
come back here: no new tabs, no floating panes.
"""
import os, shutil, subprocess, sys, termios, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import card, deckconf, migrate, tips, version, zoom

PHOSPHOR = os.path.join(REPO, "phosphor")
STEPS = os.path.join(deckconf.data_dir(), "steps")
STOCK_TABS = {"COMMS", "WORK", "SYS", "CLOUD", "DECK", "HELP", "NOTES"}

# the actions, as cards: the panel lays them out in as many columns as the
# pane's width takes (one on a phone, two or three on a computer)
GROUPS = [("screens",  [("v", "screens",          "who's attached; kick one loose"),
                        ("p", "add a screen",     "a phone, a tablet, another computer"),
                        ("w", "browser access",   "the deck in a browser, tailnet only"),
                        ("E", "e-ink panel",      "a SolarOS panel: serve it, pair it, its lines copied")]),
          ("machines", [("m", "machines & setup", "add or remove machines, phone, notebook"),
                        ("g", "triage a host",    "pick a flagged one (or any), ask an assistant"),
                        ("j", "tail logs",        "pick a host and service, stream its logs (Ctrl-C back)"),
                        ("y", "services",         "systemd units: logs, restart, start or stop"),
                        ("t", "tunnels",          "keep your ssh LocalForward tunnels up")]),
          ("work",     [("e", "explore commands", "every phosphor command, by category"),
                        ("z", "workspaces",       "every workspace, its git state; open, diff, new"),
                        ("x", "review",           "merge/pull requests of a repo, CI and diff"),
                        ("i", "install tools",    "TUIs from their releases, no sudo"),
                        ("!", "a shell here",     "on the brain; exit comes back")]),
          ("tabs & keys", [("k", "keep a tab",    "the way you arranged it, into your profile"),
                        ("b", "tabs",             "the ones that come back: forget, reorder"),
                        ("a", "recipes",          "starter tab bundles: homelab, dev, bubble, workbench"),
                        ("o", "theme",            "the deck's color, previewed before it's kept"),
                        ("c", "shortcuts",        "the deck's keys, yours to change"),
                        ("?", "key guide",        "the keys of every installed tool")]),
          ("files & notes", [("s", "send a file", "pick one: a one-time link and QR for any screen"),
                        ("R", "receive a file", "a one-time upload link, into ~/received"),
                        ("N", "a note",           "a note or todo, as Alt-j does in any tab"),
                        ("B", "backup",           "profile, notebook, tabs.d: one file to keep")]),
          ("upkeep",   [("n", "notices & traces", "phone notices, spoken ones, verbose logs: on or off"),
                        ("d", "doctor",           "check this machine"),
                        ("M", "memory",           "what each tab and pane holds, heaviest first"),
                        ("l", "logs",             "the deck's own log, and traces per tool"),
                        ("u", "update",           "a newer Phosphor, then a restart"),
                        ("r", "restart",          "every screen comes back by itself"),
                        ("h", "manual",           "phosphor help, by topic")])]
ACTIONS = [a for _, acts in GROUPS for a in acts]
# the phosphor commands each key opens (act() below), as data: tests/doors-check.py
# counts them as those commands' doors in the deck; s is a plain shell, f and P
# show up only when the profile wants them
OPENS = {"v": ["screens"], "p": ["phone", "screen"], "s": ["send"], "R": ["receive"], "N": ["note"], "B": ["backup"], "w": ["web"], "E": ["solaros"], "m": ["setup"],
         "g": ["triage"], "j": ["tail"], "y": ["services"], "t": ["tunnel"], "e": ["commands"],
         "z": ["workspace"], "x": ["review"], "i": ["store"], "!": [], "k": ["keep"], "b": ["tabs"],
         "a": ["recipe"], "o": ["theme"], "c": ["shortcuts"], "?": ["keys"],
         "n": ["push", "tts", "trace"], "d": ["doctor"], "M": ["mem"], "l": ["logs"],
         "u": ["update", "version"], "r": ["restart"], "h": ["help"], "P": ["migrate"], "f": ["gen", "restart"]}
# a key that opens one plain command (no picker or question of the panel's
# own first) opens it as its card does: card.tap, the same as on a dashboard
TAPS = {"e", "v", "M", "m", "i", "o", "y", "z", "c", "b", "a", "?", "d", "l", "h", "P", "s", "R", "B"}
# those that end on their own output wait for q, Esc or Enter (card.waits)
WAITS = {k for k in TAPS if card.waits(OPENS[k][0])}
GAP = 2

def command(k):
    """What a key does, typed in a terminal: the deck teaches it."""
    return "phosphor " + OPENS[k][0] if OPENS.get(k) else ""   # the first: the one it's for

LINE_W = card.HEAD_W + card.LABEL_W + 1 + card.VALUE_W   # key, label, value
CARD_W = LINE_W + 5                                       # the narrowest a card gets: a little air
CMD_W = max(len(command(a[0])) for a in ACTIONS)
WIDE = LINE_W + 2 + CMD_W + 2 + 26       # room for a note's first clause: past this, another column fits

def mark(step):
    """Called where the user does what a next step asks (phone kit, coming back)."""
    try:
        os.makedirs(STEPS, exist_ok=True)
        open(os.path.join(STEPS, step), "w").close()
    except OSError:
        pass

def marked(step):
    return os.path.exists(os.path.join(STEPS, step))

def out(*a):
    try:
        return subprocess.run(list(a), capture_output=True, text=True, timeout=5).stdout
    except Exception:
        import dlog
        dlog.event_throttled("PANEL", "cmd-failed")   # never str(e): it quotes the command, home path included
        return ""

def state(prof):
    import tunnels
    d = prof.get("deck") or {}
    sess = d.get("session", "deck")
    import web
    w = web.live(prof)
    running = w["published"] or w["server"]
    import workspace
    s = {"session": sess, "web": running, "web_local": running and not w["published"],
         "web_mismatch": w["flag"] != running,
         "screens": None,
         # the demo has no watchdog of its own: no line, rather than a warning that's always on
         "timer": None if d.get("demo") else
                  out("systemctl", "--user", "is-active", sess + ".timer").strip() == "active",
         "tunnels": [tunnels.active(t["host"]) for t in deckconf.tunnels(prof)],
         "dirty_workspaces": len(workspace.dirty_workspaces()),
         "profile_changed": deckconf.profile_changed(),
         "restart_pending": deckconf.restart_pending(sess),
         "version": version.current()["version"], "channel": version.current()["channel"],
         "news": version.news(), "migrate": len(migrate.pending())}
    try:
        import dlog, push, solaros, tts
        s["solaros"] = bool(solaros.serve_mode(prof))
        s["notices"] = (push.get_config(prof)["enabled"] + tts.get_config(prof)["enabled"]
                        + bool(dlog.active_traces()))
    except Exception:          # a value the card can't show, never a panel that won't draw
        import dlog
        dlog.event_throttled("PANEL", "state-failed")
    version.check_later()
    if os.environ.get("ZELLIJ"):
        import screens         # the same count as the screens card's
        s["screens"] = screens.attached(screens.sessions(prof))
        if (s["screens"] or 0) >= 2:
            mark("screens")
    return s

def steps(prof):
    tabs = [t.get("name", "") for t in prof.get("tabs", [])]
    return [("leave with Ctrl-q, come back with deck", marked("returned")),
            ("watch it from two screens at once",      marked("screens")),
            ("put it on your phone (p)",               marked("phone")),
            ("add another machine (m)",                len(deckconf.hosts(prof)) > 1),
            ("make a tab yours: + in the tab bar, keep", any(n not in STOCK_TABS for n in tabs))]

# the keys whose value the panel's own state() knows; the rest come from
# their command's --json, in the background (card.Live)
OWN = {"v", "w", "t", "E", "n", "u"}   # z: its dirty count, else its --json

def live_names():
    """The commands card.Live keeps a value of, for the DECK."""
    return [OPENS[a[0]][0] for a in ACTIONS if a[0] not in OWN and len(OPENS[a[0]]) == 1]

def value(k, st, live=None):
    """(value, warn) a key's card shows."""
    if k == "v" and st.get("screens") is not None:
        return str(st["screens"]), False
    if k == "w":
        if st.get("web_mismatch"):
            return "half", True
        return ("local" if st.get("web_local") else "on") if st.get("web") else "off", False
    if k == "t":
        tu = st.get("tunnels") or []
        return ("%d/%d up" % (sum(tu), len(tu)) if tu else "none"), sum(tu) < len(tu)
    if k == "z" and st.get("dirty_workspaces"):
        return "%d dirty" % st["dirty_workspaces"], True
    if k == "E" and "solaros" in st:
        return "on" if st["solaros"] else "off", False
    if k == "n" and "notices" in st:
        return ("%d on" % st["notices"] if st["notices"] else "off"), False
    if k == "u":
        return ("new", True) if st.get("news") else (None, False)
    if live and len(OPENS.get(k, [])) == 1:
        return live.get(OPENS[k][0])
    return None, False

def cards(prof, st, with_steps=True, live=None):
    """(title, items): an item is (key or "", text, note, warn, value)."""
    deck = []
    if st["timer"] is not None:
        deck.append(("", "watchdog", "", not st["timer"], "on" if st["timer"] else "OFF"))
    if st.get("migrate"):
        deck.append(("P", "profile migrate", "", True, "%d step%s" % (st["migrate"], "" if st["migrate"] == 1 else "s")))
    cs = [("deck", deck)] if deck else []
    todo = steps(prof)
    if with_steps and not all(done for _, done in todo):
        cs.append(("next steps", [("", text, "", None if done else "todo", None) for text, done in todo]))
    return cs + [(t, [(k, label, note) + value(k, st, live)[::-1] for k, label, note in acts])
                 for t, acts in GROUPS]

def item(it, cw, notes, cmd_w=0):
    k, text, note, warn, val = it
    if warn is None:                      # a next step already done
        return "  " + OK + " " + DIM + text[:cw - 4] + RST
    if warn == "todo":                    # a next step still to do
        return "  " + DIM + "·" + RST + " " + FG + text[:cw - 4] + RST
    cmd = command(k)
    return card.line(k, text, val, cmd.ljust(cmd_w) if notes and cmd else cmd,
                     note if notes else "", cw, warn is True)

def layout(cs, w, avail):
    """The fewest columns that show every card at once, so the notes get
    room; as many as fit if none does (then it scrolls). A wide screen gets
    as many columns as still keep the notes, not one long stretched one."""
    most = max(1, min(len(cs), (w + GAP) // (CARD_W + GAP)))
    least = max(1, min(most, (w + GAP) // (WIDE + GAP)))
    height = lambda col: sum(len(x[1]) + 2 for x in col)
    for n in range(least, most + 1):
        cw = (w - GAP * (n - 1)) // n
        best = None
        # each card into the shortest column: in their order, else the
        # tallest first (they pack closer), each column still in order
        for order in (list(cs), sorted(cs, key=lambda c: -len(c[1]))):
            cols = [[] for _ in range(n)]
            for c in order:
                h = [height(col) for col in cols]
                cols[h.index(min(h))].append(c)
            cols = [sorted(col, key=cs.index) for col in cols]
            tall = max(height(col) - 1 for col in cols if col)
            if best is None or tall < best[0]:
                best = (tall, cols)
            if tall <= avail:
                break
        if best[0] <= avail or n == most:
            return best[1], cw

def draw(prof, st, w, rows, off=0, with_steps=True, live=None):
    """The lines, the tap targets ({row: [(x0, x1, key)]}, 1-based like the
    mouse) and how far it scrolls. live: a card.Live for the values the
    panel doesn't know itself."""
    L, hit = [], {}
    ver = "v" + st["version"] + (" nightly" if st.get("channel") == "nightly" else "")
    L.append(pad(BLOOM + " PHOSPHOR DECK" + RST + DIM + " · " + st["session"] + RST, w - len(ver) - 1)
             + DIM + ver + RST)
    # what wants doing now, one line, always: a wrapped line would shift every tap target below it
    if st.get("profile_changed"):
        L.append(" " + AMB + "profile changed: f applies it" + RST)
        hit[len(L)] = [(1, w, "f")]       # a tap on that line applies it too
    elif st.get("restart_pending"):
        L.append(" " + AMB + "applied, the deck hasn't restarted yet: f restarts it" + RST)
        hit[len(L)] = [(1, w, "f")]
    elif st["news"]:
        L.append(" " + AMB + st["news"] + ": u" + RST)
        hit[len(L)] = [(1, w, "u")]
    else:
        keys = {}
        for k, cmds in OPENS.items():           # a command two keys open: the first one's
            for c in cmds:
                if k not in "fP": keys.setdefault(c, k)
        tip = tips.pick(keys)
        if tip and w >= 40:                   # did you know: one thing you may have forgotten
            L.append(vcut(" " + DIM + "did you know? " + RST + MUTE + tip[1] + RST, w))
            key = keys.get(tip[0])
            if key:
                hit[len(L)] = [(1, w, key)]   # a tap on it does it
        else:
            L.append(" " + DIM + "a key or a tap" + RST)
    avail = max(3, rows - 3)
    cols, cw = layout(cards(prof, st, with_steps, live), w, avail)
    notes = cw >= LINE_W + 2 + CMD_W + 16     # a note cut at a word still says something
    body, spots = [], []                  # spots: (body row, x0, x1, key)
    for c, col in enumerate(cols):
        x0, r = c * (cw + GAP), 0
        for title, items in col:
            if r:
                r += 1                    # the gap between two cards
            while len(body) <= r + len(items):
                body.append([""] * len(cols))
            body[r][c] = rule(title, cw)
            cmd_w = max(len(command(it[0])) for it in items)   # the notes line up, card by card
            for i, it in enumerate(items):
                body[r + 1 + i][c] = item(it, cw, notes, cmd_w)
                if it[0]:
                    spots.append((r + 1 + i, x0 + 1, x0 + cw, it[0]))
            r += 1 + len(items)
    maxoff = max(0, len(body) - avail)
    off = max(0, min(off, maxoff))
    top = len(L)
    for line in body[off:off + avail]:
        L.append("".join(pad(x, cw) + (" " * GAP if i < len(line) - 1 else "") for i, x in enumerate(line)).rstrip())
    for r, x0, x1, k in spots:
        if off <= r < off + avail:
            hit.setdefault(top + r - off + 1, []).append((x0, x1, k))
    L.append(DIM + "  " + ("↑↓ more · " if maxoff else "") + "? the keys of every tool" + RST)
    return L[:rows], hit, maxoff

def at(hit, x, y):
    """The key under a tap, if any."""
    for x0, x1, k in hit.get(y, []):
        if x0 <= x <= x1:
            return k
    return None

def pause():
    """Every action that ends on its own output waits here, with the same
    keys (q, Esc, Enter) as the TUIs the other actions open."""
    back()

def act(k, st):
    from init import yes
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    P = lambda *a: subprocess.run([sys.executable, PHOSPHOR] + list(a))
    try:
        if k in TAPS:
            card.tap(OPENS[k][0])
            if k in WAITS:
                pause()
        elif k == "p":
            P("phone"); pause()
        elif k == "N":
            P("note", "--here")
        elif k == "w":
            P("web", "status")
            print()
            if st["web"] or st.get("web_mismatch"):
                # every choice spelled out: anything else (q, Enter) changes nothing
                sys.stdout.write("  " + AMB + "t" + RST + " a new login token · " + AMB + "o" + RST
                                 + " turn it off · " + DIM + "q · Enter: back " + RST); sys.stdout.flush()
                try:
                    a = (getkey() or "").lower()
                except (termios.error, OSError, ValueError):
                    a = ""
                print()
                if a == "t":
                    P("web", "token")
                elif a == "o":
                    P("web", "off")
                else:
                    return
            elif yes("turn it on? your tailnet's devices only, with a login token (the deck restarts)", False):
                P("web", "on")
            pause()
        elif k == "E":
            import solaros
            P("solaros", "status")
            print()
            if solaros.serve_mode(deckconf.load()[0]):
                # every choice spelled out: anything else (q, Enter) changes nothing
                sys.stdout.write("  " + AMB + "p" + RST + " pair a panel · " + AMB + "o" + RST
                                 + " stop serving · " + DIM + "q · Enter: back " + RST); sys.stdout.flush()
                try:
                    a = (getkey() or "").lower()
                except (termios.error, OSError, ValueError):
                    a = ""
                print()
                if a == "p":
                    P("solaros", "pair")
                elif a == "o":
                    P("solaros", "off")
                else:
                    return
            elif yes("serve it? the glance on the LAN behind a token, its two lines on the clipboard", False):
                if getattr(P("solaros", "on"), "returncode", 1) == 0 and not solaros.paired() and \
                        yes("pair a panel now? its key, your Enter", True):
                    P("solaros", "pair")
            pause()
        elif k == "t":
            import tunnels
            tunnels.interactive()
        elif k == "k":
            P("keep", "--pick"); pause()
        elif k == "g":
            P("triage"); pause()
        elif k == "j":
            hosts = deckconf.hosts(deckconf.load()[0] or {})
            if not hosts:
                print(DIM + "  no hosts in your profile." + RST); pause()
            else:
                import edit
                picked = edit.pick("phosphor tail -- pick a host", [(h["name"], h.get("role", "")) for h in hosts])
                if picked:
                    try:
                        svc = input("  service (blank: plain journalctl, or docker/NAME, podman/NAME): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        svc = ""
                    P(*(["tail", picked[0]] + ([svc] if svc else [])))
        elif k == "x":
            if not (deckconf.exe("glab") or deckconf.exe("gh")):
                print(DIM + "  review needs glab (GitLab) or gh (GitHub; i installs it)." + RST); pause()
            else:
                import newtab
                folder = newtab.review_folder(deckconf.load()[0] or {}, shutil.get_terminal_size((60, 20)).lines)
                if folder:
                    subprocess.run([sys.executable, PHOSPHOR, "review"], cwd=folder)
        elif k == "!":
            print(DIM + "  a shell on this machine. exit (or Ctrl-d) comes back to the panel." + RST)
            subprocess.run([deckconf.shell(deckconf.load()[0]), "-l"])
        elif k == "u":
            P("version", "--new")
            if yes("update Phosphor now? the deck restarts and every screen comes back", True):
                P("update"); pause()
        elif k == "r":
            if yes("restart the deck? every screen comes back by itself", False):
                P("restart"); pause()
        elif k == "n":
            import dlog, edit, push, tts
            traces = dlog.active_traces()
            got = edit.pick("notices & traces", [
                ("push", ("on" if push.get_config()["enabled"] else "off") + " -- notices on a phone (ntfy)"),
                ("voice", ("on" if tts.get_config()["enabled"] else "off") + " -- notices spoken aloud"),
                ("trace", ("%d on" % len(traces) if traces else "none on") + " -- a tool's verbose log")])
            sys.stdout.write("\x1b[?1049l\x1b[2J\x1b[H"); sys.stdout.flush()
            if got:
                P({"push": "push", "voice": "tts", "trace": "trace"}[got[0]])
        elif k == "f":
            # a hand edit of deck.toml (or tabs.d) only shows after gen and a
            # restart; never done behind anyone's back: the restart closes every pane
            import dlog
            if st.get("profile_changed"):
                print("  the profile changed since the last " + PH + "phosphor gen" + RST
                      + ": the deck still runs the one before.")
                go = yes("apply it now? phosphor gen, then a restart (every screen comes back by itself)", False)
                if go:
                    rc = P("gen").returncode
                    dlog.event("PANEL", "apply", "gen rc=%d" % rc)
                    if rc != 0:
                        print(AMB + "  gen failed (exit %d): nothing restarted. Fix the profile, then f again." % rc + RST)
                        go = False
                    else:
                        deckconf.mark_applied()   # until the deck restarts, f offers the restart alone
            else:
                print("  the profile is applied, but the deck running now started before that:")
                print("  it shows the change once it restarts.")
                go = yes("restart now? (every screen comes back by itself)", False)
            if go:
                rc = P("restart").returncode
                dlog.event("PANEL", "apply", "restart rc=%d" % rc)
                if rc != 0:
                    print(AMB + "  the restart didn't go through (exit %d): f tries again, "
                          "phosphor logs says why." % rc + RST)
            pause()
    except KeyboardInterrupt:
        print()
    finally:
        # a TUI that ran here may have left the alternate screen on its way out
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()

def main():
    if not sys.stdin.isatty():
        print("phosphor panel is the DECK tab: it needs a terminal"); return 1
    keys = {a[0] for a in ACTIONS}
    ALIAS = {"S": "s"}                  # send was S until 2.4.1, beside s, the shell: either sends now
    mono_stdout()                       # an e-ink screen: the ! and the words carry it
    live = card.Live(live_names())
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    prof, st, last, off = {}, None, 0, 0
    try:
        while True:
            if time.time() - last > 3:
                prof = deckconf.load()[0] or {}
                st = state(prof); last = time.time()
            cols, rows = shutil.get_terminal_size((60, 30))
            lines, hit, maxoff = draw(prof, st, cols, rows, off, live=live)
            off = min(off, maxoff)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[J"); sys.stdout.flush()
            k = getkey(1.0)
            if isinstance(k, tuple):
                if k[0] == "MOUSE" and k[4] and k[1] in (64, 65):     # the wheel, two fingers
                    off = max(0, min(maxoff, off + (3 if k[1] == 65 else -3)))
                    continue
                k = at(hit, k[2], k[3]) if k[0] == "MOUSE" and k[1] == 0 and k[4] else None
            k = ALIAS.get(k, k)
            step = {"\x1b[B": 1, "\x1b[A": -1, "\x1b[6~": rows - 4, "\x1b[5~": 4 - rows}.get(k)
            if step:
                off = max(0, min(maxoff, off + step))
            elif k == "q":                  # keys.md, "Esc and q": run offers Enter to open it again
                break
            elif k == "\x1b":
                zoom.back()
            elif k in keys or (k == "f" and (st.get("profile_changed") or st.get("restart_pending"))) or (k == "P" and st.get("migrate")):
                act(k, st); last = 0
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
