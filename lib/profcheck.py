"""The profile's known keys, and what's wrong with one: a misspelled key
(`thme`), a key in the wrong table (`[tts] enable`), a value outside its
choices (`theme = "p1"`). TOML parses all of those fine and the deck
just ignores them, so gen and doctor say so instead.

The tables here follow doc/manual/profile.md (tests/profile-schema-check.py
keeps the two in step). Warnings only: an unknown key never stops gen."""
import difflib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BOOL = "true or false"

def _themes():
    import deck_setup
    return tuple(k for k, _ in deck_setup.THEMES)

# key -> None (anything), BOOL, or a tuple of the values it takes
DECK = {"session": None, "command": None, "theme": "themes", "mount_root": None,
        "projects": None, "mesh": ("auto", "tailscale", "headscale", "none"),
        "bar": ("tabs", "compact", "full"), "editor": None, "shell": None,
        "connect": ("ssh", "mosh"), "web": BOOL, "web_port": None, "notifier": BOOL,
        "graphs": ("braille", "blocks"), "face": None, "splash": BOOL,
        "notify_seconds": None, "demo": BOOL, "tour": BOOL,
        "tts": BOOL,                     # deprecated: share/deprecations.json
        "version": None}                 # migrate.py checks it
HOST = {"name": None, "role": ("brain", "work", "desktop", "storage", "node", "viewer"),
        "local": BOOL, "ssh": None, "user": None, "ip": None, "mount": None,
        "mounts": None, "fleet": BOOL}
TAB = {"name": None, "split": ("rows", "cols"), "panes": None}
PANE = {"cmd": None, "args": None, "ssh": None, "reconnect": BOOL, "size": None,
        "cwd": None, "needs_size": BOOL, "alt": BOOL, "split": ("rows", "cols"),
        "panes": None}
TABLES = {
    "deck": DECK,
    "keys": {"edit": None, "new_tab": None, "note": None, "zoom": None, "leave": None,
             "controls": None, "tabs": None, "panes": None},
    "notes": {"folder": None, "require_project": BOOL},
    "mentions": {"prepare": None, "by": None, "prompt": None, "timeout": None},
    "prometheus": {"url": None, "interval": None, "gauges": None},
    "ci": {"interval": None, "pipelines": None},
    "tts": {"enabled": BOOL, "voice": None, "glados_path": None, "volume": None,
            "fleet_alerts": BOOL},
    "push": {"enabled": BOOL, "url": None, "topic": None, "token": None,
             "priority": ("min", "low", "default", "high", "max"), "title": None,
             "open_web": BOOL, "clip": BOOL},
    "services": {"interval": None, "extra": None},
}
GAUGE = {"name": None, "type": ("gauge", "arc", "sparkline"), "query": None, "min": None,
         "max": None, "warn": None, "crit": None, "unit": None}
PIPELINE = {"name": None, "provider": ("github", "gitlab"), "repo": None, "branch": None,
            "token": None, "url": None}
TUNNEL = {"host": None, "config": None}
SCREEN = {"tabs": None, "land": None, "theme": "themes", "graphs": ("braille", "blocks"),
          "skip": None}
SECTIONS = sorted(set(TABLES) | {"hosts", "tabs", "tunnels", "screens", "alerts"})


def _guess(key, known):
    m = difflib.get_close_matches(key, list(known), n=1, cutoff=0.6)
    return m[0] if m else None


def _val(v):
    """A value the way the profile writes it: "p1", not 'p1'."""
    return json.dumps(v, ensure_ascii=False, default=str)   # a TOML date too


def _table(where, t, known, out):
    """Unknown keys and bad values in one table: append (where, what)."""
    if not isinstance(t, dict):
        out.append((where, "should be a table")); return
    for k, v in t.items():
        if k not in known:
            g = _guess(k, known)
            out.append((where, "unknown key %s%s" % (k, ": %s?" % g if g else "")))
            continue
        spec = known[k]
        if spec == "themes":
            spec = _themes()
        if spec == BOOL and not isinstance(v, bool):
            out.append((where, "%s is %s, not %s" % (k, BOOL, _val(v))))
        elif isinstance(spec, tuple) and v not in spec:
            out.append((where, "%s = %s isn't one of %s" % (k, _val(v), ", ".join(spec))))


def _array(where, items, known, out, name_key="name"):
    if not isinstance(items, list):
        out.append(("[%s]" % where, "should be [[%s]] blocks" % where)); return
    for i, t in enumerate(items):
        label = t.get(name_key) if isinstance(t, dict) else None
        _table("[[%s]] %s" % (where, label or "#%d" % (i + 1)), t, known, out)


def _panes(where, panes, out):
    if not isinstance(panes, list):
        out.append((where, "panes is a list of panes")); return
    for p in panes:
        if isinstance(p, dict):
            _table(where, p, PANE, out)
            if "panes" in p:
                _panes(where, p["panes"], out)


def _alerts(val, hosts, out):
    """[alerts] and [alerts.HOST]: a metric's [warn, bad], for a host the profile has."""
    import limits
    if not isinstance(val, dict):
        out.append(("[alerts]", "should be a table")); return
    def metrics(where, t):
        for k, v in t.items():
            if k not in limits.DEFAULTS:
                g = _guess(k, limits.DEFAULTS)
                out.append((where, "unknown key %s%s" % (k, ": %s?" % g if g else "")))
            elif limits.problem(k, v):
                out.append((where, "%s = %s %s" % (k, _val(v), limits.problem(k, v))))
    metrics("[alerts]", {k: v for k, v in val.items() if not isinstance(v, dict)})
    for host, t in val.items():
        if isinstance(t, dict):
            if host not in hosts:
                g = _guess(host, [h for h in hosts if h])
                out.append(("[alerts.%s]" % host, "no such host in [[hosts]]%s" % (": %s?" % g if g else "")))
            metrics("[alerts.%s]" % host, t)


def tabs(where, items, out):
    _array(where, items, TAB, out)
    for t in items if isinstance(items, list) else []:
        if isinstance(t, dict) and "panes" in t:
            _panes("[[tabs]] %s" % t.get("name", "?"), t["panes"], out)


def problems(prof):
    """What gen and doctor warn about: [(where, what's wrong)], where is
    the table ("[deck]", "[[hosts]] nimbus", "[[tabs]] SYS", "[screens.phone]")."""
    out = []
    for sec, val in (prof or {}).items():
        if not isinstance(val, (dict, list)):
            # a key above every [table] header: TOML puts it nowhere useful
            home = [(g, t) for t, known in TABLES.items()
                    for g in [_guess(sec, known)] if g]
            out.append(("profile", "%s is above every [table]%s" % (
                sec, ": %s in [%s]?" % home[0] if home else "")))
        elif sec not in SECTIONS:
            g = _guess(sec, SECTIONS)
            out.append(("[%s]" % sec, "unknown table%s" % (": [%s]?" % g if g else "")))
        elif sec == "hosts":
            _array("hosts", val, HOST, out)
        elif sec == "tabs":
            tabs("tabs", val, out)
        elif sec == "tunnels":
            _array("tunnels", val, TUNNEL, out, "host")
        elif sec == "alerts":
            _alerts(val, [h.get("name") for h in prof.get("hosts", []) if isinstance(h, dict)]
                    if isinstance(prof.get("hosts"), list) else [], out)
        elif sec == "screens":
            if isinstance(val, dict):        # its shape is kinds.problems()'s
                for k, v in val.items():
                    if isinstance(v, dict):
                        _table("[screens.%s]" % k, v, SCREEN, out)
        else:
            _table("[%s]" % sec, val, TABLES[sec], out)
            if sec == "prometheus" and isinstance(val, dict) and "gauges" in val:
                _array("prometheus.gauges", val["gauges"], GAUGE, out)
            if sec == "ci" and isinstance(val, dict) and "pipelines" in val:
                _array("ci.pipelines", val["pipelines"], PIPELINE, out)
    import cli                   # still read, but on its way out (doc/manual/api.md)
    for d in cli.deprecations("key"):
        t = (prof or {}).get(d["table"])
        if isinstance(t, dict) and d["name"] in t:
            out.append(("[%s]" % d["table"], cli.warning(d)))
    return out


def tabs_d_problems():
    """The same for every tabs.d file: [(file name, what's wrong)]."""
    import deckconf
    out, seen = [], {}
    for t, src in deckconf.tabs_d():
        seen.setdefault(src, []).append(t)
    for src, items in seen.items():
        got = []
        tabs("tabs", items, got)
        out += [("tabs.d/" + os.path.basename(src), "%s: %s" % (w, what)) for w, what in got]
    return out
