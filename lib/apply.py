"""phosphor apply - a changed profile, live, without a restart when it can (#124).

`phosphor gen` writes the files; apply decides what the running deck needs
from what gen just wrote, and does only that:

- a tab whose layout changed (tab-NAME.kdl) is reloaded in place, the way
  Alt-r's "put it back" does it: a new tab from its layout at the same
  place, the old one closed. Every other tab keeps its panes and processes.
- a tab added to the profile is opened at its place; one taken out of it
  is closed (a tab you opened with + is never in the profile: left alone).
- tabs in a new order are moved into it (#127), each keeping its panes; a
  tab you opened with + stays right after the tab it followed.
- what zellij or the deck's service read only when they start (config.kdl:
  keys and theme; the bars every tab shares; the deck's own unit: PATH,
  editor, shell; how the session starts) needs a restart: apply says which.
- fleet mounts, tunnels and SolarOS are units of their own: reloaded and
  (re)started, the deck isn't.
- the attach command, ~/fleet's links, rclone.conf: nothing to do now.
- a kind of screen's session ([screens.KIND], deck-phone) gets the same,
  from its own tab layouts (gen writes them in a folder named after it):
  its changed tabs reloaded, its new ones opened, its order set (#126).
  With nobody attached to it they're pending for it, like the deck's; its
  bars, theme or graphs changed: it takes those when it restarts, named.

A tab whose panes hold something a reload loses (a shell, an editor, an
assistant: anything that isn't a deck tool or a viewer) is reloaded or
closed only when you say so: apply names those panes and asks once.
Without a terminal to ask on and without --yes, it leaves them, and any
restart, pending: the DECK tab's line and f offer them again.
"""
import io, contextlib, json, os, re, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, hotswap, proc

PHOSPHOR = os.path.join(REPO, "phosphor")
MARK = " ✎"                               # lib/edit.py's: the tab is being edited
DOT = " ●"                                # mentions/tabmark's: "SYS ●3", unseen notices
TAB = re.compile(r'^    tab name="([^"]*)"', re.M)

# Programs whose pane loses nothing on a reload: they show, they don't keep.
VIEWERS = {"btop", "htop", "top", "ctop", "gping", "ping", "mtr", "iftop", "nload", "bmon",
           "nvtop", "glances", "watch", "sleep", "tail", "journalctl", "less", "yazi",
           "lazygit", "lazydocker", "k9s", "matterhorn"}
# deck tools that do keep something of their own on screen
KEEPS = {"ask", "shell", "voice"}


def sname(prof):
    return ((prof or {}).get("deck") or {}).get("session", "deck")


# ── what gen wrote, and what the deck needs from it ────────────
def tabs_of(layout):
    """The tab names of a session layout gen wrote, in order."""
    return TAB.findall(layout or "")

def skeleton(layout):
    """A session layout without its tabs and its header: the bars and the
    + tab's template, what every tab shares and only a restart rereads."""
    out, inside = [], False
    for l in (layout or "").splitlines():
        if l.startswith('    tab name="'):
            inside = True
        elif inside and l == "    }":
            inside = False
        elif not inside and not l.startswith("//"):
            out.append(l)
    return "\n".join(out)

def compare(old_layout, new_layout):
    """Tabs added, taken out, in a new order, and why a restart (the bars),
    between a session layout before and after."""
    new = tabs_of(new_layout)
    if old_layout is None:
        return {"add": [], "remove": [], "order": [], "restart": ["no earlier session layout to compare with"]}
    old = tabs_of(old_layout)
    return {"add": [n for n in new if n not in old], "remove": [n for n in old if n not in new],
            # moved into it live, no restart (#127)
            "order": new if [n for n in old if n in new] != [n for n in new if n in old] else [],
            "restart": [] if skeleton(old_layout) == skeleton(new_layout) else ["the bars every tab shares"]}

def plan(old_layout, new_layout, changed, prof, screens=None):
    """What the running deck needs, from the files gen changed and the
    session layout before and after. screens: {kind: (its session layout
    before, after)}; each kind's session gets the same in "kinds" (#126),
    and one that needs a restart is named in "screens"."""
    import gen, kinds
    sess = sname(prof)
    p = {"reload": [], "add": [], "remove": [], "order": [], "restart": [], "units": [], "screens": [], "kinds": {}}
    new = tabs_of(new_layout)
    old = tabs_of(old_layout) if old_layout else None
    byfile = {"tab-%s.kdl" % n.lower(): n for n in new}
    layouts = {kinds.layout(prof, k): kinds.session(prof, k) for k in kinds.kinds(prof)}
    dirs = {kinds.tab_dir(kinds.session(prof, k), sess): k for k in kinds.kinds(prof)}
    themes = os.path.dirname(gen.ZTHEME)
    reload_in = {}
    for path in changed:
        b, d = os.path.basename(path), os.path.dirname(path)
        if path == os.path.join(gen.ZDIR, sess + ".kdl"):
            continue                                  # compared below, tab by tab
        if path in layouts:
            if screens is None:                       # nothing to compare it with: named
                p["screens"].append(layouts[path])
            continue
        if d in dirs:
            reload_in.setdefault(dirs[d], []).append(b)
        elif d == gen.ZDIR and b in byfile:
            if old is None or byfile[b] in old:       # a new tab is opened below, not reloaded
                p["reload"].append(byfile[b])
        elif d == themes and b.startswith("phosphor-"):
            pass                                      # a kind of screen's theme: its layout says it
        elif d == gen.UDIR:
            if b.startswith(sess + "."):
                p["restart"].append("the deck's service (%s: PATH, editor, shell)" % b)
            else:
                p["units"].append(b)
        elif path == gen.ZCONF:
            p["restart"].append("config.kdl (keys, theme)")
        elif path == gen.ZTHEME:
            p["restart"].append("the theme")
        elif path in (gen.YAZI_THEME_PATH, gen.YAZI_KEYMAP_PATH, gen.BTOP_THEME_PATH, gen.BTOP_CONF_PATH):
            p["restart"].append("yazi and btop's colors and keys")
        elif b == "%s-up.sh" % sess:
            p["restart"].append("how the session starts (%s)" % b)
        elif d == os.path.join(gen.HOME, ".local/bin") or b == "rclone.conf" or os.path.islink(path):
            pass                                      # the next attach / mount / look reads it
        else:
            p["restart"].append(b)                    # nothing knows it: the safe answer
    c = compare(old_layout, new_layout)
    p["restart"] += c.pop("restart")
    p.update(c)
    for k, (was, now) in (screens or {}).items():
        c = compare(was, now)
        if was is not None and was == now and not reload_in.get(k):
            continue
        if c["restart"]:
            p["screens"].append(kinds.session(prof, k))
            continue
        names = tabs_of(now)
        byname = {"tab-%s.kdl" % n.lower(): n for n in names}
        c["reload"] = [byname[b] for b in reload_in.get(k, []) if b in byname and byname[b] not in c["add"]]
        del c["restart"]
        if any(c.values()):
            p["kinds"][kinds.session(prof, k)] = c
    for k in p:
        if isinstance(p[k], list):
            p[k] = list(dict.fromkeys(p[k]))
    p["screens"] = sorted(set(p["screens"]))
    return p


# ── the live session ───────────────────────────────────────────
def zj(sess, *a):
    z = proc.zellij()
    if not z:
        return ""
    try:
        return subprocess.run([z, "-s", sess, "action"] + list(a), capture_output=True,
                              text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

def live(sess):
    """True when that session is up (not an EXITED one zellij keeps)."""
    z = proc.zellij()
    if not z:
        return False
    try:
        out = subprocess.run([z, "list-sessions", "-n"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(l.split()[:1] == [sess] and "EXITED" not in l for l in out.splitlines())

def clients(sess):
    """The screens attached. Nobody is a real answer, but a busy zellij
    gives it too: asked again for a few seconds before it's believed."""
    end = time.time() + 3
    while True:
        got = [l for l in zj(sess, "list-clients").splitlines()[1:] if l.strip()]
        if got or time.time() > end:
            return got
        time.sleep(0.3)

def base(name):
    """A live tab's name as the profile has it: "SYS ●3" and "SYS ✎ Alt r" are SYS."""
    return name.split(DOT)[0].split(MARK)[0].strip()

def _listed(sess, *what):
    """A list action's JSON. A live session always has tabs and panes, so
    an empty or unreadable answer is zellij busy, not the truth: asked
    again for a few seconds (under load one came back empty, and a tab was
    taken for gone)."""
    end = time.time() + 5
    while True:
        try:
            got = json.loads(zj(sess, *what) or "[]")
        except ValueError:
            got = []
        if got or time.time() > end:
            return got
        time.sleep(0.3)

def tabs(sess):
    """[{tab_id, position, name, base, active}] of the session, in order."""
    got = _listed(sess, "list-tabs", "-j", "-s")
    for t in got:
        t["base"] = base(t.get("name") or "")
    return sorted(got, key=lambda t: t["position"])

def panes(sess):
    return [p for p in _listed(sess, "list-panes", "-a", "-j") if not p.get("is_plugin")]

def program(argv):
    """The program a pane runs, past `phosphor run ... --` and an
    interpreter: ("phosphor", TOOL) for a deck tool, (name, None) else."""
    if not argv:
        return None, None
    if "--" in argv and any(os.path.basename(a) == "phosphor" for a in argv[:argv.index("--")]):
        argv = argv[argv.index("--") + 1:]
    for i, a in enumerate(argv[:3]):
        if os.path.basename(a) == "phosphor":
            return "phosphor", (argv[i + 1] if i + 1 < len(argv) else None)
    prog = os.path.basename(argv[0])
    if re.match(r"python[\d.]*$", prog) and len(argv) > 1:
        prog = os.path.basename(argv[1])
    return prog, None

def holds(argv):
    """What a reload of this pane would lose, in a word, or None."""
    name, tool = program(argv)
    if name is None:
        return None                               # nothing runs there any more
    if name == "phosphor":
        return ("phosphor " + tool) if tool in KEEPS else None
    return None if name in VIEWERS else name

def keeping(sess, tab_id):
    """["SHELL (bash)", ...]: the panes of a tab that hold something."""
    out, mine = [], [p for p in panes(sess) if p["tab_id"] == tab_id]
    if not mine:                          # zellij didn't say: never taken for "nothing to lose"
        return ["its panes (zellij didn't list them)"]
    for p in mine:
        what = holds(hotswap.argv_of(sess, p["id"]))
        if what:
            title = (p.get("title") or "").strip()
            if "/" in title or title.lower() == what:
                title = ""                # a command line, not a name: never a path on screen
            out.append("%s (%s)" % (title, what) if title else what)
    return out


# ── doing it ───────────────────────────────────────────────────
def layout_of(name, where=None):
    """A tab's own layout: the deck's, or in where (a kind's folder, #126)."""
    import gen
    return os.path.join(where or gen.ZDIR, "tab-%s.kdl" % name.lower())

def _pids(sess, tab_id):
    return [pid for p in panes(sess) if p["tab_id"] == tab_id for pid in hotswap.pane_procs(sess, p["id"])]

def _new_tab(sess, layout, name):
    """A tab from that layout, last, without moving anybody's focus (a
    switch zellij answers late landed after apply had put you back, #130):
    its tab id, or None if zellij didn't make it."""
    had = {t["tab_id"] for t in tabs(sess)}
    out = zj(sess, "new-tab", "--no-focus", "--layout", layout, "--name", name).strip()
    if out.isdigit():
        return int(out)
    end = time.time() + 5                 # a busy zellij makes it and says nothing: found by name
    while time.time() < end:
        new = [t["tab_id"] for t in tabs(sess) if t["tab_id"] not in had and t["base"] == name]
        if new:
            return new[-1]
        time.sleep(0.3)
    return None

def _move_to(sess, tid, pos):
    """Tab tid to position pos, by its id: nobody's focus moves. Read back
    after the moves (a busy zellij drops an action) and done again."""
    for _ in range(3):
        t = next((t for t in tabs(sess) if t["tab_id"] == tid), None)
        if t and t["position"] == pos:
            return
        if not t:                         # not listed yet
            time.sleep(0.3)
            continue
        for _ in range(abs(t["position"] - pos)):
            zj(sess, "move-tab", "-t", str(tid), "left" if t["position"] > pos else "right")
        time.sleep(0.2)

def reload(sess, name, where=None):
    """Alt-r's "put it back", from outside the tab: its layout as a new tab
    at the same place, then the old one closed, and whatever was left
    hidden under a screen in it killed. False if the tab isn't there."""
    now = tabs(sess)
    t = next((t for t in now if t["base"] == name), None)
    if not t or not os.path.exists(layout_of(name, where)):
        import dlog
        dlog.event("APPLY", "reload-missed", "%s among %d tabs" % (name, len(now)))
        return False
    old = _pids(sess, t["tab_id"])
    tid = _new_tab(sess, layout_of(name, where), name)
    if tid is None:
        return False
    _move_to(sess, tid, t["position"])
    if t.get("active"):                   # you were on it: on the new one before the old one goes
        zj(sess, "go-to-tab-by-id", str(tid))
    zj(sess, "close-tab-by-id", str(t["tab_id"]))
    _reap(old)
    return True

def close(sess, name):
    t = next((t for t in tabs(sess) if t["base"] == name), None)
    if not t:
        return False
    old = _pids(sess, t["tab_id"])
    zj(sess, "close-tab-by-id", str(t["tab_id"]))
    _reap(old)
    return True

def open_tab(sess, name, after, where=None):
    """A tab new to the profile, right after the profile tab before it
    that's open (`after`, in profile order), or first."""
    if not os.path.exists(layout_of(name, where)):
        return False
    names = [t["base"] for t in tabs(sess)]
    prev = [n for n in after if n in names]
    pos = names.index(prev[-1]) + 1 if prev else 0
    tid = _new_tab(sess, layout_of(name, where), name)
    if tid is None:
        return False
    _move_to(sess, tid, pos)
    return True

def target_order(live_tabs, names):
    """The tab ids of the session in the profile's order: each profile tab
    followed by the tabs that came right after it (a + tab keeps its
    neighbour), the ones before any profile tab first. live_tabs: tabs()."""
    lead, groups, seen = [], [], set()
    for t in live_tabs:
        if t["base"] in names and t["base"] not in seen:
            seen.add(t["base"])
            groups.append((names.index(t["base"]), [t["tab_id"]]))
        elif groups:
            groups[-1][1].append(t["tab_id"])
        else:
            lead.append(t["tab_id"])
    return lead + [i for _, g in sorted(groups, key=lambda g: g[0]) for i in g]

def reorder(sess, names):
    """The live tabs moved into the profile's order: each one out of place
    moved left to its place by its id, nobody's focus moved (#130). Read back from list-tabs after every move (a busy zellij
    drops an action): the names moved, or None if it didn't get there."""
    moved, now = [], tabs(sess)
    want = target_order(now, names)       # once: a + tab's neighbour is the one it had before any move
    for _ in range(3 * max(1, len(names))):
        now = tabs(sess)
        ids = [t["tab_id"] for t in now]
        if not now or sorted(ids) != sorted(want):
            return None
        i = next((i for i, (a, b) in enumerate(zip(ids, want)) if a != b), None)
        if i is None:
            return moved
        j = ids.index(want[i])
        for _ in range(j - i):
            zj(sess, "move-tab", "-t", str(want[i]), "left")
        time.sleep(0.2)
        if now[j]["base"] not in moved:
            moved.append(now[j]["base"])
    return None

def _reap(pids):
    time.sleep(0.5)
    for p in pids:                        # a pane hidden under a screen outlives its closed tab
        try: os.kill(p, signal.SIGKILL)
        except OSError: pass

def my_tab(sess):
    """The tab this runs in, if it runs in a pane of that session."""
    if os.environ.get("ZELLIJ_SESSION_NAME") != sess or not os.environ.get("ZELLIJ_PANE_ID"):
        return None
    me = int(os.environ["ZELLIJ_PANE_ID"])
    p = next((p for p in panes(sess) if p["id"] == me), None)
    return p and base(p["tab_name"])

def later(argv):
    """`apply --later reload|close NAME [SESSION]`: the tab apply itself
    runs in, once apply is done with the rest (closing it ends apply). A
    kind of screen's session reloads it from its own folder."""
    import kinds
    what, name = argv[0], argv[1]
    deck = sname(deckconf.load()[0])
    sess = argv[2] if len(argv) > 2 else deck
    time.sleep(1.0)
    print(time.strftime("%H:%M:%S"), "apply", what, name, sess, flush=True)
    if what == "reload":
        reload(sess, name, kinds.tab_dir(sess, deck))
    else:
        close(sess, name)
    return 0


# ── the command ────────────────────────────────────────────────
def gen_quietly(prof, path, dry, changed):
    """gen, its warnings shown, the rest of its report only when it fails."""
    import gen
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = gen.run(prof, path, dry=dry, changed=changed)
    lines = buf.getvalue().splitlines()
    if rc:
        print("\n".join(lines))
    else:
        for l in lines:
            if WARN in l or BAD in l:
                print(l)
    return rc

def ask(q, default, yes_all):
    if yes_all:
        return True
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False                      # nobody to ask: left pending, said so
    import init
    return init.yes(q, default)

def run(argv):
    if argv[:1] == ["--later"]:
        return later(argv[1:])
    dry = "--dry-run" in argv or "-n" in argv
    yes_all = "--yes" in argv or "-y" in argv
    as_json = "--json" in argv
    prof, path = deckconf.load()
    if not prof:
        print("  no profile: phosphor init writes one"); return 1
    import gen, kinds
    sess = sname(prof)
    def was(path):
        try:
            return open(path).read()
        except OSError:
            return None
    old = was(os.path.join(gen.ZDIR, sess + ".kdl"))
    kold = {k: was(kinds.layout(prof, k)) for k in kinds.kinds(prof)}   # each kind's, before gen (#126)
    changed = []
    out = sys.stdout
    if as_json:
        sys.stdout = io.StringIO()        # only the JSON on stdout
    try:
        rc = gen_quietly(prof, path, dry, changed)
        if rc:
            if as_json:
                out.write(json.dumps({"ok": False, "gen": rc}) + "\n")
            return rc
        ctx = gen.Ctx(prof)
        if not ctx.is_brain():
            print(row(OK, "this machine", "a screen: its deck command is up to date, the brain applies the rest"))
            if as_json:
                out.write(json.dumps({"ok": True, "screen": True}) + "\n")
            return 0
        new = gen.deck_kdl(prof, ctx, path)
        p = plan(old, new, changed, prof, {k: (o, gen.kind_kdl(prof, k, path)) for k, o in kold.items()})
        # its theme or graphs: in its session's environment, only a restart changes it
        p["screens"] = sorted(set(p["screens"]) | {kinds.session(prof, k) for k in kold if kinds.restyled(prof, k)})
        res = act(sess, prof, p, dry, yes_all)
    finally:
        sys.stdout = out
    if as_json:
        print(json.dumps(dict(res, ok=True, plan=p)))
    return 0

VERB = {"reload": "reloaded in place", "close": "closed: not in the profile any more", "open": "opened"}

def act(sess, prof, p, dry, yes_all):
    """Does the plan, or as much of it as it may; says what it did: in the
    deck's session, then in each kind of screen's (#126)."""
    import kinds
    res = {"reloaded": [], "opened": [], "closed": [], "moved": [], "units": [], "restarted": False,
           "pending": {"tabs": [], "restart": [], "order": False}, "screens": {}}
    pend = deckconf.apply_pending(sess) or {}
    kpend = deckconf.screens_pending()    # what an earlier apply left in a kind's session
    names = [t["name"] for t in deckconf.effective_tabs(prof)]
    p["restart"] = list(dict.fromkeys(p["restart"] + pend.get("restart", [])))
    print("\n" + rule("apply" + (" (dry-run)" if dry else "")))

    if p["units"]:
        units(p["units"], dry, res)
    for s in p["screens"]:
        print(row(DIM + "·" + RST, s, "takes it when it restarts", note="phosphor restart"))

    if not live(sess):
        print(row(OK, "the deck", "isn't running: it starts with this", note="phosphor up"))
        if not dry: deckconf.mark_applied()
        return res
    later_kinds = {s: {"tabs": (kpend.get(s) or {}).get("tabs", []) + w.get("reload", []) + w.get("add", [])
                       + w.get("remove", []), "order": bool(w.get("order") or (kpend.get(s) or {}).get("order"))}
                   for s, w in dict(kpend, **p["kinds"]).items()}
    if p["restart"]:
        print(row(WARN, "restart", "needed for " + "; ".join(p["restart"])))
        if dry:
            return res
        if ask("restart the deck now? every pane closes, every screen comes back by itself", False, yes_all):
            # marked first: a session that starts after the mark has it all
            deckconf.mark_applied(restart=p["restart"], screens=later_kinds)
            res["restarted"] = subprocess.run([sys.executable, PHOSPHOR, "restart"]).returncode == 0
            if not res["restarted"]:
                print(AMB + "  the restart didn't go through: f tries again, phosphor logs says why" + RST)
            return res
        res["pending"] = {"tabs": [], "restart": p["restart"], "order": False}
        deckconf.mark_applied(restart=p["restart"], screens=later_kinds)
        print("  " + DIM + "left for later: f in the DECK tab, or phosphor apply" + RST)
        return res

    got = in_session(sess, names, p, pend, None, "the deck", dry, yes_all)
    for k in ("reloaded", "opened", "closed", "moved"):
        res[k] = got[k]
    res["pending"]["tabs"], res["pending"]["order"] = got["left"], got["left_order"]
    own = got["own"] and (sess,) + got["own"]
    bykind = {kinds.session(prof, k): k for k in kinds.kinds(prof)}
    left_kinds = {}
    for ks in sorted(set(p["kinds"]) | set(kpend)):
        if ks not in bykind:
            continue                      # its block is gone from the profile: nothing to lay out
        if not live(ks):
            if ks in p["kinds"]:
                print(row(DIM + "·" + RST, ks, "isn't running: it starts with this"))
            continue
        knames = [t["name"] for t in kinds.tabs(prof, bykind[ks])]
        got = in_session(ks, knames, p["kinds"].get(ks) or {}, kpend.get(ks) or {},
                         kinds.tab_dir(ks, sess), ks, dry, yes_all)
        res["screens"][ks] = {k: got[k] for k in ("reloaded", "opened", "closed", "moved")}
        res["screens"][ks]["pending"] = {"tabs": got["left"], "order": got["left_order"]}
        if got["left"] or got["left_order"]:
            left_kinds[ks] = {"tabs": got["left"], "order": got["left_order"]}
        own = own or (got["own"] and (ks,) + got["own"])
    if dry:
        return res
    deckconf.mark_applied(tabs=res["pending"]["tabs"], order=res["pending"]["order"], screens=left_kinds)
    if res["pending"]["tabs"] or res["pending"]["order"] or left_kinds:
        print("  " + DIM + "left as they are: f in the DECK tab (or phosphor apply) asks again" + RST)
    if own:
        osess, w, mine = own
        print("  " + DIM + "this tab goes last: it " + ("reloads" if w == "reload" else "closes") + " in a moment" + RST)
        log = open(os.path.join(deckconf.cache_dir(), "apply.log"), "a")
        subprocess.Popen([sys.executable, PHOSPHOR, "apply", "--later", w, mine, osess],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        if osess == sess:
            res["reloaded" if w == "reload" else "closed"].append(mine)
        else:
            res["screens"][osess]["reloaded" if w == "reload" else "closed"].append(mine)
    return res

def in_session(sess, names, want, pend, where, label, dry, yes_all):
    """One live session's tabs: reloaded, opened, closed and moved into the
    profile's order (names), the tabs' layouts from where. want: the plan's
    reload/add/remove/order for it; pend: what an earlier apply left. Says
    what it left (no screen attached, a tab that holds something) and the
    tab this runs in, if it has to go: that one goes last, by the caller."""
    out = {"reloaded": [], "opened": [], "closed": [], "moved": [], "left": [], "left_order": False, "own": None}
    rl, ad, rm = list(want.get("reload") or []), list(want.get("add") or []), list(want.get("remove") or [])
    live_tabs = {}
    for t in tabs(sess):
        live_tabs.setdefault(t["base"], t)
    for n in pend.get("tabs", []):        # what an earlier apply left: reload, close or open
        (rl if n in names and n in live_tabs else ad if n in names else rm).append(n)
    rl, ad, rm = (list(dict.fromkeys(x)) for x in (rl, ad, rm))
    work = [("reload", n) for n in rl if n in live_tabs] + \
           [("close", n) for n in rm if n in live_tabs] + \
           [("open", n) for n in ad if n not in live_tabs]
    edited = [n for w, n in work if MARK in live_tabs.get(n, {}).get("name", "")]
    for n in edited:                      # Alt-r's save or put back decides that one
        print(row(DIM + "·" + RST, n, "being edited: left as it is"))
    work = [(w, n) for w, n in work if n not in edited]
    # a new order in the profile, or one an earlier apply left; tabs you moved by hand
    # are left where you put them until the profile's order changes
    order = bool(want.get("order") or pend.get("order"))
    if not work and not order:
        print(row(OK, label, "already shows it: nothing to reload"))
        return out
    if not clients(sess):
        # never new-tab (or move one) in a session nobody is attached to (AGENTS.md)
        print(row(WARN, label, "no screen attached: its tabs are reloaded once one is", note="f in its DECK tab"))
        out["left"], out["left_order"] = [n for _, n in work], order
        return out

    risky = {n: keeping(sess, live_tabs[n]["tab_id"]) for w, n in work if w != "open"}
    risky = {n: k for n, k in risky.items() if k}
    if risky:
        for n, k in risky.items():
            print(row(WARN, n, "holds " + ", ".join(k), note="a reload loses it"))
        if dry or not ask("reload %s anyway?" % (", ".join(risky) if len(risky) > 1 else "it"), False, yes_all):
            out["left"] = list(risky)
            work = [(w, n) for w, n in work if n not in risky]
    if dry:
        for w, n in work:
            print(row(AMB, n, "would be " + VERB[w]))
        if order:
            print(row(AMB, "the tabs", "would be moved into the profile's order"))
        return out

    mine = my_tab(sess)
    focus = next((t["base"] for t in tabs(sess) if t.get("active")), None)
    for w, n in work:
        if n == mine:
            continue
        done = reload(sess, n, where) if w == "reload" else close(sess, n) if w == "close" \
            else open_tab(sess, n, names[:names.index(n)], where)
        if done:
            print(row(OK, n, VERB[w]))
            out[{"reload": "reloaded", "close": "closed", "open": "opened"}[w]].append(n)
        else:                             # zellij didn't find it or didn't answer: not done, kept
            print(row(WARN, n, "not done: zellij didn't answer in time", note="f tries again"))
            out["left"].append(n)
    if order:                             # after the rest: opened and reloaded tabs are in place by then
        moved = reorder(sess, names)
        if moved is None:
            print(row(WARN, "the tabs", "not all in the profile's order: zellij didn't answer in time",
                      note="f tries again"))
            out["left_order"] = True
        elif moved:
            print(row(OK, "the tabs", "moved into the profile's order: " + ", ".join(moved)))
            out["moved"] = moved
    if focus:                             # nothing above moves it; checked anyway: a busy zellij drops a switch
        for _ in range(3):
            now = tabs(sess)
            back = next((t for t in now if t["base"] == focus), None)
            if not back or back.get("active"):
                break
            zj(sess, "go-to-tab-name", back["name"])
            time.sleep(0.3)
    own = next((w for w, n in work if n == mine), None)
    out["own"] = own and (own, mine)
    return out

def units(names, dry, res):
    """Mounts, tunnels, SolarOS: their own units, reloaded and (re)started
    on their own; the deck isn't restarted for them."""
    if dry:
        for u in names:
            print(row(AMB, u, "would be (re)started"))
        return
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    for u in names:
        if u.endswith(".timer") or not u.endswith(".service"):
            continue
        on = subprocess.run(["systemctl", "--user", "is-enabled", u], capture_output=True,
                            text=True).stdout.strip() == "enabled"
        r = subprocess.run(["systemctl", "--user"] + (["try-restart", u] if on else ["enable", "--now", u]),
                           capture_output=True)
        print(row(OK if r.returncode == 0 else BAD, u, ("restarted" if on else "started") if r.returncode == 0
                  else "failed: journalctl --user -u " + u))
        res["units"].append(u)

def main():
    return run(sys.argv[1:])               # the dispatcher left ["phosphor-apply", args...]

if __name__ == "__main__":
    sys.exit(main() or 0)
