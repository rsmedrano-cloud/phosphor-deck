"""A deck for each kind of screen: [screens.KIND] in the profile.
Project Phosphor Deck.

zellij sizes every tab to the smallest screen attached to it, with no
setting for that, so a phone's layout can't live in the desktop's session.
A kind of screen with a [screens.KIND] block gets a session of its own,
`<session>-KIND` (deck-phone, deck-eink), on the same brain: the notebook,
the fleet, ~/fleet and the profile are shared; the panes aren't (a shell
on the phone isn't the desktop's).

    [screens.phone]
    tabs   = ["SYS", "NOTES", "COMMS"]   # which tabs, in this order (default: all)
    land   = "NOTES"                     # the tab you arrive on (default: the first)
    theme  = "paper"                     # default: the deck's
    graphs = "blocks"                    # default: the deck's
    skip   = ["phosphor adjutant"]          # panes left out of its tabs, by their cmd (+ args)

The screen says which kind it is when it attaches (`deck --screen phone`,
written there by `phosphor phone` / `phosphor screen --as KIND`); a kind
without a block, or no kind at all, gets the deck's own session, as always.
The session is made when that screen first comes in, never by the
watchdog, and `phosphor restart` / `down` take them all along.
"""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

NAME = re.compile(r"^[a-z][a-z0-9]{0,15}$")
# what the screen's panes are told, through the session's own environment
ENV = ("PHOSPHOR_SCREEN", "PHOSPHOR_THEME", "PHOSPHOR_GRAPHS")


def base(prof):
    return ((prof or {}).get("deck") or {}).get("session", "deck")


def kinds(prof):
    """{kind: its block}, only the well-formed ones, in the profile's order."""
    raw = (prof or {}).get("screens") or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if NAME.match(str(k)) and isinstance(v, dict)}


def problems(prof):
    """What gen and doctor warn about: [(kind, what's wrong)]."""
    out = []
    raw = (prof or {}).get("screens") or {}
    if not isinstance(raw, dict):
        return [("screens", "should be tables: [screens.phone]")]
    names = {t.get("name") for t in deckconf.effective_tabs(prof)}
    for k, v in raw.items():
        if not NAME.match(str(k)):
            out.append((str(k), "a kind is lowercase letters and digits, 16 at most"))
            continue
        if not isinstance(v, dict):
            out.append((k, "should be a table: [screens.%s]" % k))
            continue
        for t in v.get("tabs") or []:
            if t not in names:
                out.append((k, "no tab named %s" % t))
        if v.get("land") and v["land"] not in [t["name"] for t in tabs(prof, k)]:
            out.append((k, "land = %s isn't one of its tabs" % v["land"]))
        if v.get("graphs") not in (None, "braille", "blocks"):
            out.append((k, "graphs is braille or blocks"))
        if v.get("skip") is not None and not (isinstance(v["skip"], list)
                                              and all(isinstance(c, str) for c in v["skip"])):
            out.append((k, 'skip is a list of commands: ["phosphor adjutant"]'))
    return out


def session(prof, kind):
    """The session a screen of this kind attaches to."""
    return "%s-%s" % (base(prof), kind) if kind in kinds(prof) else base(prof)


def sessions(prof):
    """Every screen session the profile can make (not the deck's own)."""
    return [session(prof, k) for k in kinds(prof)]


def _prune(panes, skip):
    """panes without the ones whose cmd is in skip. A split left with one pane
    becomes that pane, in the split's place and size: zellij has no use for a
    split of one."""
    out = []
    for n in panes:
        if n.get("panes"):
            kids = _prune(n["panes"], skip)
            if not kids:
                continue
            if len(kids) == 1:
                n = dict(kids[0], **({"size": n["size"]} if "size" in n else {}))
            else:
                n = dict(n, panes=kids)
        elif str(n.get("cmd") or "").strip() in skip:
            continue
        out.append(n)
    return out


def tabs(prof, kind):
    """The tabs a kind's session lays out: its list, in its order, or all of them,
    minus the panes it skips (a tab left with none goes too)."""
    every = deckconf.effective_tabs(prof)
    k = kinds(prof).get(kind) or {}
    want = k.get("tabs")
    if want:
        by = {t.get("name"): t for t in every}
        every = [by[n] for n in want if n in by]
    skip = {str(c).strip() for c in k.get("skip") or []}
    if not skip:
        return every
    out = []
    for t in every:
        if not t.get("panes"):
            out.append(t)
            continue
        left = _prune(t["panes"], skip)
        if left:
            out.append(dict(t, panes=left))
    return out


def land(prof, kind):
    names = [t["name"] for t in tabs(prof, kind)]
    want = (kinds(prof).get(kind) or {}).get("land")
    return want if want in names else (names[0] if names else None)


def deck(prof, kind):
    """The profile's [deck] as this kind's panes see it."""
    d = dict((prof or {}).get("deck") or {})
    k = kinds(prof).get(kind) or {}
    for key in ("theme", "graphs"):
        if k.get(key):
            d[key] = k[key]
    d["notifier"] = False        # no floating panes there: see [deck] notifier
    return d


def theme(prof, kind):
    """The palette of this kind's session, by its ui name."""
    import ui
    t = deck(prof, kind).get("theme", "p31")
    t = ui.ALIASES.get(t, t)
    return t if t in ui.PALETTES else "p31"


def zellij_theme(prof, kind):
    """The zellij theme name this kind's session starts with."""
    return "phosphor-" + theme(prof, kind)


def env(prof, kind):
    """The environment its session is made with: every pane inherits it."""
    e = dict(os.environ)
    for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID") + ENV:
        e.pop(k, None)
    e["PHOSPHOR_SCREEN"] = kind
    d = deck(prof, kind)
    e["PHOSPHOR_THEME"] = theme(prof, kind)
    if d.get("graphs"):
        e["PHOSPHOR_GRAPHS"] = d["graphs"]
    return e


def graphs(prof):
    """braille or blocks, for this pane: its screen's, else the deck's."""
    return os.environ.get("PHOSPHOR_GRAPHS") or \
        ((prof or {}).get("deck") or {}).get("graphs", "braille")


def layout(prof, kind):
    return os.path.expanduser("~/.config/zellij/layouts/%s.kdl" % session(prof, kind))


def made_dir():
    return os.path.join(deckconf.cache_dir(), "screens")


def made():
    """Screen sessions made on this brain, even by a profile that's since
    dropped their block: restart and down take these along too."""
    try:
        return sorted(os.listdir(made_dir()))
    except OSError:
        return []


def forget(name):
    try:
        os.remove(os.path.join(made_dir(), name))
    except OSError:
        pass


def all_sessions(prof):
    """What restart and down stop besides the deck: its screens' sessions."""
    return sorted(set(sessions(prof)) | set(made()))


def create(zj, prof, kind):
    """Make the kind's session in the background, laid out from its own
    layout. True once it's there. Never called for the deck's own."""
    s = session(prof, kind)
    if not os.path.exists(layout(prof, kind)):
        return False
    subprocess.run([zj, "delete-session", s], capture_output=True)   # a dead one would come back dead
    r = subprocess.run([zj, "--layout", layout(prof, kind), "attach", "--create-background", s,
                        "options", "--theme", zellij_theme(prof, kind)],
                       env=env(prof, kind), capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        os.makedirs(made_dir(), exist_ok=True)
        open(os.path.join(made_dir(), s), "w").close()
        try:
            import hotswap
            hotswap.record(s)               # what its panes start with (see update)
        except Exception:
            pass
    return r.returncode == 0


def arg(argv):
    """--screen KIND (or --screen=KIND) out of argv: (kind or '', the rest)."""
    out, kind, it = [], "", iter(argv)
    for a in it:
        if a == "--screen":
            kind = next(it, "")
        elif a.startswith("--screen="):
            kind = a.split("=", 1)[1]
        else:
            out.append(a)
    return kind.strip().lower(), out
