"""phosphor tabmark - a generic "<TAB> <mark>N" on any tab's name, the same
mechanism mentions.py already uses for COMMS (rename-tab-by-id, no floating
panes -- see #14) but for `phosphor notify` in general: the tab it names
with --tab, or SYS with none. With `notifier = false` (the default) a
notification otherwise leaves no trace on screen until you happen to look
at SYS's adjutant -- this is the "you'd have missed it" fix for that.

`bump()` is called straight from `phosphor notify`: one more unseen for
that tab, renamed right away. `tick()`, run every few seconds from the same
loop mentions.py's own marker already runs in (fleet's always-on worker),
clears a tab's mark the moment someone's actually looking at it -- COMMS is
skipped here on purpose, mentions.py already owns that one.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, mentions

STATE = os.path.join(deckconf.cache_dir(), "tabmarks.json")
SKIP = {mentions.CHAT}

def load():
    try:
        with open(STATE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    open(STATE, "w").write(json.dumps(st))

def find_tab(sess, base):
    """(tab id, current name, {pane ids}) for the open tab named `base`
    (its mark stripped first), or None -- nothing to rename if it isn't
    open right now."""
    try:
        panes = json.loads(mentions.zj(sess, "list-panes", "-t", "-c", "-j") or "[]")
    except ValueError:
        return None
    for p in panes:
        if p.get("is_plugin"):
            continue
        if (p.get("tab_name") or "").split(mentions.MARK)[0].strip() != base:
            continue
        tid = p["tab_id"]
        ids = {"terminal_%d" % q["id"] for q in panes
               if q.get("tab_id") == tid and not q.get("is_plugin")}
        return tid, p.get("tab_name", ""), ids
    return None

def rename(sess, base, n):
    tab = find_tab(sess, base)
    if not tab:
        return
    tid, name, _ = tab
    want = base + ("%s%d" % (mentions.MARK, n) if n else "")
    if want != name:
        mentions.zj(sess, "rename-tab-by-id", str(tid), want)

def bump(sess, tab):
    """One more unseen for `tab` (or SYS with none); renamed right away."""
    tab = (tab or "").strip() or "SYS"
    if tab in SKIP:
        return
    st = load()
    st[tab] = st.get(tab, 0) + 1
    save(st)
    rename(sess, tab, st[tab])

def tick(sess):
    """Clear a tab's mark once someone's actually on it. Cheap when nothing
    is marked: one state-file read, no zellij calls."""
    st = load()
    marked = {t: n for t, n in st.items() if n}
    if not marked:
        return
    changed = False
    for tab in marked:
        found = find_tab(sess, tab)
        if not found:
            continue
        _, _, ids = found
        on = any(l.split()[1] in ids for l in mentions.zj(sess, "list-clients").splitlines()[1:]
                 if len(l.split()) >= 2)
        if on:
            st[tab] = 0
            rename(sess, tab, 0)
            changed = True
    if changed:
        save(st)
