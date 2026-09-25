"""phosphor panel - the DECK tab: the deck's own state, what's left to set
up, and every phosphor action one key (or one tap) away.

It runs on the brain, so phosphor always has a place to run even when every
other tab is an ssh to somewhere else. Actions run in this same pane and
come back here: no new tabs, no floating panes.
"""
import os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, version

PHOSPHOR = os.path.join(REPO, "phosphor")
STEPS = os.path.join(deckconf.data_dir(), "steps")
STOCK_TABS = {"COMMS", "WORK", "SYS", "CLOUD", "DECK", "HELP", "NOTES"}

ACTIONS = [("e", "explore commands",  "every phosphor command, by category"),
           ("v", "screens",          "who's attached; kick one loose"),
           ("p", "add a screen",     "a phone, a tablet, another computer"),
           ("m", "machines & color", "add or remove machines, pick the phosphor"),
           ("w", "browser access",   "the deck in a browser, tailnet only"),
           ("t", "tunnels",          "keep your ssh LocalForward tunnels up"),
           ("i", "install tools",    "TUIs from their releases, no sudo"),
           ("k", "keep a tab",       "the way you arranged it, into your profile"),
           ("g", "triage a host",    "pick a flagged one (or none flagged: back), ask an assistant"),
           ("j", "tail logs",        "pick a host and service, stream its logs (Ctrl-C back)"),
           ("c", "shortcuts",        "the deck's keys, yours to change"),
           ("b", "tabs",             "the ones that come back: forget, reorder"),
           ("a", "recipes",          "starter tab bundles: homelab, dev, bubble, workbench"),
           ("s", "a shell here",     "on the brain; exit comes back"),
           ("d", "doctor",           "check this machine"),
           ("l", "logs",             "the deck's own log, and traces per tool"),
           ("u", "update",           "a newer Phosphor, then a restart"),
           ("r", "restart",          "every screen comes back by itself"),
           ("h", "manual",           "phosphor help, by topic")]

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
         "version": version.current()["version"], "channel": version.current()["channel"],
         "news": version.news()}
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

def draw(prof, st, w, rows, with_steps=True):
    L, hit = [], {}
    ver = "v" + st["version"] + (" nightly" if st.get("channel") == "nightly" else "")
    L.append(pad(BLOOM + " PHOSPHOR DECK" + RST + DIM + " · " + st["session"] + RST, w - len(ver) - 1)
             + DIM + ver + RST)
    parts = [AMB + st["news"] + ": u" + RST + FG] if st["news"] else []
    if st["screens"] is not None:
        parts.append("%d screen%s in" % (st["screens"], "" if st["screens"] == 1 else "s"))
    parts.append("watchdog " + ("on" if st["timer"] else AMB + "OFF" + RST + FG))
    parts.append(AMB + "web half on" + RST + FG if st.get("web_mismatch") else
                 "web " + (("local" if st.get("web_local") else "on") if st["web"] else "off"))
    tu = st["tunnels"]
    parts.append("tunnels %d/%d up" % (sum(tu), len(tu)) if tu else "no tunnels")
    if st.get("dirty_workspaces"):
        n = st["dirty_workspaces"]
        parts.append(AMB + "%d workspace%s dirty" % (n, "" if n == 1 else "s") + RST + FG)
    # one line, always: a wrapped line would shift every tap target below it
    while len(parts) > 1 and vlen(" " + " · ".join(parts)) > w:
        parts.pop()
    L.append(" " + FG + " · ".join(parts) + RST)
    todo = steps(prof)
    if with_steps and not all(done for _, done in todo):
        L.append("")
        L.append(rule("next steps", w))
        for text, done in todo:
            L.append("  " + (OK if done else DIM + "·" + RST) + " " + (DIM if done else FG) + text + RST)
    L.append("")
    L.append(rule("actions", w))
    notes = 22 + max(len(a[2]) for a in ACTIONS) <= w       # all of them or none
    for k, label, note in ACTIONS:
        line = "  " + AMB + k + RST + "  " + FG + "%-17s" % label + RST
        if notes:
            line += " " + DIM + note + RST
        hit[len(L) + 1] = k           # mouse rows are 1-based
        L.append(line)
    L.append("")
    L.append(DIM + "  a key or a tap" + RST)
    if len(L) > rows and with_steps:
        return draw(prof, st, w, rows, with_steps=False)
    return L[:rows], hit

def pause():
    try: input("\n  " + DIM + "Enter to go back " + RST)
    except (EOFError, KeyboardInterrupt): pass

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
                # every choice spelled out: Enter changes nothing
                try:
                    a = input("  " + AMB + "t" + RST + " a new login token · " + AMB + "o" + RST
                              + " turn it off · " + DIM + "Enter: back " + RST).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    a = ""
                if a == "t":
                    P("web", "token")
                elif a == "o":
                    P("web", "off")
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
        elif k == "c":
            P("shortcuts")
        elif k == "b":
            P("tabs")
        elif k == "a":
            P("recipe")
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
    prof, st, last = {}, None, 0
    try:
        while True:
            if time.time() - last > 3:
                prof = deckconf.load()[0] or {}
                st = state(prof); last = time.time()
            cols, rows = shutil.get_terminal_size((60, 30))
            lines, hit = draw(prof, st, min(cols, 100), rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[J"); sys.stdout.flush()
            k = getkey(1.0)
            if isinstance(k, tuple):
                k = hit.get(k[3]) if k[0] == "MOUSE" and k[1] == 0 and k[4] else None
            if k in keys:
                act(k, st); last = 0
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
