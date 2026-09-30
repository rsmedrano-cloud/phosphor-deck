"""phosphor panel - the DECK tab: the deck's own state, what's left to set
up, and every phosphor action one key (or one tap) away.

It runs on the brain, so phosphor always has a place to run even when every
other tab is an ssh to somewhere else. Actions run in this same pane and
come back here: no new tabs, no floating panes.
"""
import os, shutil, subprocess, sys, termios, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, version

PHOSPHOR = os.path.join(REPO, "phosphor")
STEPS = os.path.join(deckconf.data_dir(), "steps")
STOCK_TABS = {"COMMS", "WORK", "SYS", "CLOUD", "DECK", "HELP", "NOTES"}

# the actions, as cards: the panel lays them out in as many columns as the
# pane's width takes (one on a phone, two or three on a computer)
GROUPS = [("screens",  [("v", "screens",          "who's attached; kick one loose"),
                        ("p", "add a screen",     "a phone, a tablet, another computer"),
                        ("w", "browser access",   "the deck in a browser, tailnet only")]),
          ("machines", [("m", "machines & setup", "add or remove machines, phone, notebook"),
                        ("g", "triage a host",    "pick a flagged one (or any), ask an assistant"),
                        ("j", "tail logs",        "pick a host and service, stream its logs (Ctrl-C back)"),
                        ("y", "services",         "systemd units: logs, restart, start or stop"),
                        ("t", "tunnels",          "keep your ssh LocalForward tunnels up")]),
          ("work",     [("e", "explore commands", "every phosphor command, by category"),
                        ("z", "workspaces",       "every workspace, its git state; open, diff, new"),
                        ("x", "review",           "merge/pull requests of a repo, CI and diff"),
                        ("i", "install tools",    "TUIs from their releases, no sudo"),
                        ("s", "a shell here",     "on the brain; exit comes back")]),
          ("tabs & keys", [("k", "keep a tab",    "the way you arranged it, into your profile"),
                        ("b", "tabs",             "the ones that come back: forget, reorder"),
                        ("a", "recipes",          "starter tab bundles: homelab, dev, bubble, workbench"),
                        ("o", "theme",            "the deck's color, previewed before it's kept"),
                        ("c", "shortcuts",        "the deck's keys, yours to change"),
                        ("?", "key guide",        "the keys of every installed tool")]),
          ("upkeep",   [("n", "notices & traces", "phone notices, spoken ones, verbose logs: on or off"),
                        ("d", "doctor",           "check this machine"),
                        ("l", "logs",             "the deck's own log, and traces per tool"),
                        ("u", "update",           "a newer Phosphor, then a restart"),
                        ("r", "restart",          "every screen comes back by itself"),
                        ("h", "manual",           "phosphor help, by topic")])]
ACTIONS = [a for _, acts in GROUPS for a in acts]
NOTE_W = max(len(a[2]) for a in ACTIONS)
CARD_W = 34                   # the narrowest a card gets: key, label, a little air
GAP = 2

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

def zellij():
    z = os.path.expanduser("~/.local/bin/zellij")
    return z if os.path.exists(z) else (shutil.which("zellij") or "zellij")

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
         "timer": out("systemctl", "--user", "is-active", sess + ".timer").strip() == "active",
         "tunnels": [tunnels.active(t["host"]) for t in deckconf.tunnels(prof)],
         "dirty_workspaces": len(workspace.dirty_workspaces()),
         "profile_changed": deckconf.profile_changed(),
         "version": version.current()["version"], "channel": version.current()["channel"],
         "news": version.news(), "two_panes": bool(two_panes(prof))}
    version.check_later()
    if os.environ.get("ZELLIJ"):
        # the header line aside, one line per screen looking at the deck
        s["screens"] = max(0, len(out(zellij(), "action", "list-clients").strip().splitlines()) - 1)
        if s["screens"] >= 2:
            mark("screens")
    return s

def steps(prof):
    tabs = [t.get("name", "") for t in prof.get("tabs", [])]
    return [("leave with Ctrl-q, come back with deck", marked("returned")),
            ("watch it from two screens at once",      marked("screens")),
            ("put it on your phone (p)",               marked("phone")),
            ("add another machine (m)",                len(deckconf.hosts(prof)) > 1),
            ("make a tab yours: + in the tab bar, keep", any(n not in STOCK_TABS for n in tabs))]

def two_panes(prof):
    """The tab that still has the key guide beside the panel (every profile
    before the panel took the whole tab): its name, or None."""
    for t in (prof or {}).get("tabs", []):
        cmds = [(q.get("cmd") or "").strip() for q in t.get("panes") or []]
        if sorted(cmds) == ["phosphor keys", "phosphor panel"]:
            return t.get("name")
    return None

def one_pane():
    """The panel takes the whole tab: the key guide beside it goes (it's ?
    now). Only the profile is written; f applies it, like any other edit."""
    import keep
    from init import yes
    name = two_panes(deckconf.load()[0] or {})
    if not name:
        return
    print("  the %s tab has the key guide beside the panel. The panel can take the whole" % name)
    print("  tab now, laying its cards out for the screen's width; the key guide is " + AMB + "?" + RST + " in it.")
    if yes("write %s as one pane into your profile? (a backup is kept; f applies it)" % name, True):
        keep.save(name, keep.block(name, [{"cmd": "phosphor panel"}]))

def cards(prof, st, with_steps=True):
    """(title, items): an item is (key or "", text, note, warn)."""
    deck = []
    if st["screens"] is not None:
        deck.append(("v", "%d screen%s in" % (st["screens"], "" if st["screens"] == 1 else "s"), "", False))
    deck.append(("", "watchdog " + ("on" if st["timer"] else "OFF"), "", not st["timer"]))
    web = ("web half on" if st.get("web_mismatch") else
           "web " + (("local" if st.get("web_local") else "on") if st["web"] else "off"))
    deck.append(("w", web, "", bool(st.get("web_mismatch"))))
    tu = st["tunnels"]
    deck.append(("t", "tunnels %d/%d up" % (sum(tu), len(tu)) if tu else "no tunnels", "", sum(tu) < len(tu)))
    if st.get("dirty_workspaces"):
        n = st["dirty_workspaces"]
        deck.append(("z", "%d workspace%s dirty" % (n, "" if n == 1 else "s"), "", True))
    if st.get("two_panes"):
        deck.append(("1", "this tab in one pane", "", True))
    cs = [("deck", deck)]
    todo = steps(prof)
    if with_steps and not all(done for _, done in todo):
        cs.append(("next steps", [("", text, "", None if done else "todo") for text, done in todo]))
    return cs + [(t, [(k, label, note, False) for k, label, note in acts]) for t, acts in GROUPS]

def item(it, cw, notes):
    k, text, note, warn = it
    if warn is None:                      # a next step already done
        return "  " + OK + " " + DIM + text[:cw - 4] + RST
    if warn == "todo":                    # a next step still to do
        return "  " + DIM + "·" + RST + " " + FG + text[:cw - 4] + RST
    head = "  " + (AMB + k + RST if k else " ") + "  "
    room = cw - 5
    color = AMB if warn is True else FG
    if notes and note:
        return head + color + "%-17s" % text[:17] + RST + " " + DIM + note[:max(0, room - 18)] + RST
    return head + color + text[:room] + RST

def layout(cs, w, avail):
    """The fewest columns that show every card at once, so the notes get
    room; as many as fit if none does (then it scrolls)."""
    most = max(1, min(len(cs), (w + GAP) // (CARD_W + GAP)))
    for n in range(1, most + 1):
        cw = (w - GAP * (n - 1)) // n
        cols = [[] for _ in range(n)]
        for c in cs:                      # each card into the shortest column
            h = [sum(len(x[1]) + 2 for x in col) for col in cols]
            cols[h.index(min(h))].append(c)
        tall = max(sum(len(x[1]) + 2 for x in col) - 1 for col in cols if col)
        if tall <= avail or n == most:
            return cols, cw

def draw(prof, st, w, rows, off=0, with_steps=True):
    """The lines, the tap targets ({row: [(x0, x1, key)]}, 1-based like the
    mouse) and how far it scrolls."""
    L, hit = [], {}
    ver = "v" + st["version"] + (" nightly" if st.get("channel") == "nightly" else "")
    L.append(pad(BLOOM + " PHOSPHOR DECK" + RST + DIM + " · " + st["session"] + RST, w - len(ver) - 1)
             + DIM + ver + RST)
    # what wants doing now, one line, always: a wrapped line would shift every tap target below it
    if st.get("profile_changed"):
        L.append(" " + AMB + "profile changed: f applies it" + RST)
        hit[len(L)] = [(1, w, "f")]       # a tap on that line applies it too
    elif st["news"]:
        L.append(" " + AMB + st["news"] + ": u" + RST)
        hit[len(L)] = [(1, w, "u")]
    else:
        L.append(" " + DIM + "a key or a tap" + RST)
    avail = max(3, rows - 3)
    cols, cw = layout(cards(prof, st, with_steps), w, avail)
    notes = cw >= 23 + NOTE_W
    body, spots = [], []                  # spots: (body row, x0, x1, key)
    for c, col in enumerate(cols):
        x0, r = c * (cw + GAP), 0
        for title, items in col:
            if r:
                r += 1                    # the gap between two cards
            while len(body) <= r + len(items):
                body.append([""] * len(cols))
            body[r][c] = rule(title, cw)
            for i, it in enumerate(items):
                body[r + 1 + i][c] = item(it, cw, notes)
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
        if k == "e":
            P("commands")
        elif k == "v":
            P("screens")
        elif k == "p":
            P("phone"); pause()
        elif k == "m":
            P("setup")
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
        elif k == "t":
            import tunnels
            tunnels.interactive()
        elif k == "i":
            P("store")
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
        elif k == "o":
            P("theme")
        elif k == "y":
            P("services")
        elif k == "z":
            P("workspace")
        elif k == "x":
            if not (deckconf.exe("glab") or deckconf.exe("gh")):
                print(DIM + "  review needs glab (GitLab) or gh (GitHub; i installs it)." + RST); pause()
            else:
                import newtab
                folder = newtab.review_folder(deckconf.load()[0] or {}, shutil.get_terminal_size((60, 20)).lines)
                if folder:
                    subprocess.run([sys.executable, PHOSPHOR, "review"], cwd=folder)
        elif k == "s":
            print(DIM + "  a shell on this machine. exit (or Ctrl-d) comes back to the panel." + RST)
            subprocess.run([deckconf.shell(deckconf.load()[0]), "-l"])
        elif k == "d":
            P("doctor"); pause()
        elif k == "l":
            P("logs"); pause()
        elif k == "u":
            P("version", "--new")
            if yes("update Phosphor now? the deck restarts and every screen comes back", True):
                P("update"); pause()
        elif k == "r":
            if yes("restart the deck? every screen comes back by itself", False):
                P("restart"); pause()
        elif k == "h":
            P("help"); pause()
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
        elif k == "c":
            P("shortcuts")
        elif k == "b":
            P("tabs")
        elif k == "a":
            P("recipe")
        elif k == "?":
            P("keys")
        elif k == "1":
            one_pane(); pause()
        elif k == "f":
            # a hand edit of deck.toml (or tabs.d) only shows after gen and a
            # restart; never done behind anyone's back: the restart closes every pane
            print("  the profile changed since the last " + PH + "phosphor gen" + RST
                  + ": the deck still runs the one before.")
            if yes("apply it now? phosphor gen, then a restart (every screen comes back by itself)", False):
                if P("gen").returncode == 0:
                    P("restart")
                else:
                    print(AMB + "  gen failed: nothing restarted. Fix the profile, then f again." + RST)
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
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    prof, st, last, off = {}, None, 0, 0
    try:
        while True:
            if time.time() - last > 3:
                prof = deckconf.load()[0] or {}
                st = state(prof); last = time.time()
            cols, rows = shutil.get_terminal_size((60, 30))
            lines, hit, maxoff = draw(prof, st, cols, rows, off)
            off = min(off, maxoff)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[J"); sys.stdout.flush()
            k = getkey(1.0)
            if isinstance(k, tuple):
                if k[0] == "MOUSE" and k[4] and k[1] in (64, 65):     # the wheel, two fingers
                    off = max(0, min(maxoff, off + (3 if k[1] == 65 else -3)))
                    continue
                k = at(hit, k[2], k[3]) if k[0] == "MOUSE" and k[1] == 0 and k[4] else None
            step = {"\x1b[B": 1, "\x1b[A": -1, "\x1b[6~": rows - 4, "\x1b[5~": 4 - rows}.get(k)
            if step:
                off = max(0, min(maxoff, off + step))
            elif k in keys or (k == "f" and st.get("profile_changed")) or (k == "1" and st.get("two_panes")):
                act(k, st); last = 0
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
