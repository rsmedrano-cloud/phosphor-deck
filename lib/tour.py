#!/usr/bin/env python3
"""phosphor demo --tour - the demo deck, with a guide.

Every tab of the demo gets a floating pane running this (`phosphor demo
--tour-pane`). They all show the same step, read from one small state file,
so the guide is there whichever tab you land on. Each step asks you to try
something real (switch tabs, Alt-j a note, Alt-n a tab, Alt-r save it) and
checks it happened before moving on: zellij's own tab list, the demo's
notebook and the demo's copy of the profile, never guessed.

Enter steps the guide aside (it hides on this tab) so the keys reach the
deck; it comes back on its own when the step is done. It only ever runs in
the demo's own session, its own zellij server: floating panes stay off in
the real deck (see `notifier` in the manual), and if one wedges here, that's
a repro for issue #14, not a lost session.
"""
import fcntl, json, os, subprocess, sys, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf
from ui import DIM, FG, MUTE, PH, AMB, RST, getkey

STEPS = [
    {"id": "hello", "title": "a deck you can break",
     "text": "Made-up machines, a made-up notebook: nothing here touches your real deck. "
             "Every step asks you to try one thing, and moves on once it has seen you do it."},
    {"id": "tabs", "title": "tabs",
     "text": "Each tab is one job: SYS watches the fleet, DECK has every action, NOTES the notebook. "
             "Go to NOTES: Alt-3, or tap its name in the bar at the top.",
     "check": lambda s, b: s.get("active") == "NOTES"},
    {"id": "note", "title": "a note from anywhere",
     "text": "Alt-j writes a note from whatever tab you're in, tagged with it. "
             "Press Alt-j, pick note, write a line, then an empty line saves it.",
     "check": lambda s, b: s.get("notes", 0) > b.get("notes", 0)},
    {"id": "newtab", "title": "a new tab",
     "text": "Alt-n (or + in the tab bar) opens the new-tab menu. Open one: "
             "a shell is fine.",
     "check": lambda s, b: s.get("tabs", 0) > b.get("tabs", 0)},
    {"id": "keep", "title": "keep it",
     "text": "Tabs you open by hand are gone after a restart unless you keep them. "
             "In that new tab press Alt-r, then Alt-r again, then s: it goes into the profile. "
             "Then Alt-1 to come back here.",
     "check": lambda s, b: s.get("kept", 0) > b.get("kept", 0)},
    {"id": "done", "title": "that's the deck",
     "text": "The DECK tab (Alt-2) has everything else, a key or a tap each. "
             "Leave with Alt-x; phosphor demo --stop ends the demo. "
             "On your own machine: phosphor init."},
]


def state_path():
    return os.path.join(deckconf.cache_dir(), "tour.json")


def load():
    try:
        st = json.load(open(state_path()))
        return st if isinstance(st.get("step"), int) else {"step": 0, "base": {}}
    except (OSError, ValueError):
        return {"step": 0, "base": {}}


def save(st):
    tmp = state_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_path())


def zj(*args):
    b = deckconf.exe("zellij")
    if not b:
        return ""
    try:
        return subprocess.run([b, "-s", os.environ.get("ZELLIJ_SESSION_NAME", ""), "action"] + list(args),
                              capture_output=True, text=True, timeout=8).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def live_tabs():
    """[{name, tab_id, active}] from zellij itself; [] if it didn't answer."""
    try:
        return json.loads(zj("list-tabs", "--state", "--json") or "[]")
    except ValueError:
        return []


def snapshot(tabs=None):
    """What the checks look at, right now."""
    import notes
    tabs = live_tabs() if tabs is None else tabs
    prof, _ = deckconf.load()
    return {"active": next((t.get("name") for t in tabs if t.get("active")), None),
            "tabs": len(tabs),
            "notes": len(notes.entries()),
            "kept": len((prof or {}).get("tabs") or [])}


def advance(frm, to=None, show=True):
    """Move from step `frm` to `to` (the next one by default), once: every tab's pane
    polls the same checks, and only the first to get here moves it. True if it was us."""
    to = frm + 1 if to is None else to
    lock = open(state_path() + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = load()
        if st["step"] != frm:
            return False
        tabs = live_tabs()
        save({"step": max(0, min(to, len(STEPS) - 1)), "base": snapshot(tabs)})
    finally:
        lock.close()
    # back into view on the tab you're on, if it's one of the demo's own (a tab you
    # opened by hand has no guide in it: the step said to come back)
    home = [t["name"] for t in deckconf.effective_tabs(deckconf.load()[0] or {})]
    act = next((t for t in tabs if t.get("active")), None)
    if show and act and act.get("name") in home:
        zj("show-floating-panes", "-t", str(act.get("tab_id")))
    return True


def draw(st, waiting):
    i = st["step"]
    s = STEPS[i]
    w = max(20, min(os.get_terminal_size().columns if sys.stdout.isatty() else 44, 60) - 4)
    out = ["\x1b[2J\x1b[H", "  " + PH + "TOUR" + RST + DIM + "  %d/%d" % (i + 1, len(STEPS)) + RST,
           "  " + FG + s["title"] + RST, ""]
    out += ["  " + MUTE + l + RST for l in textwrap.wrap(s["text"], w)]
    out.append("")
    if s.get("check"):
        out.append("  " + (AMB + "waiting for you..." if waiting else DIM + "Enter: try it (I'll step aside)") + RST)
    keys = ["Enter: next"] if not s.get("check") and i < len(STEPS) - 1 else []
    keys += ["h: hide", "b: back"] if i else ["h: hide"]
    keys.append("q: end the tour")
    out.append("  " + DIM + " · ".join(keys) + RST)
    sys.stdout.write("\n".join(out)); sys.stdout.flush()


def main():
    os.makedirs(deckconf.cache_dir(), exist_ok=True)
    shown, waiting, last_poll = None, False, 0.0
    while True:
        st = load()
        i = st["step"]
        if shown != (i, waiting):
            if shown and shown[0] != i:
                waiting = False
            draw(st, waiting)
            shown = (i, waiting)
        step = STEPS[i]
        if step.get("check") and time.time() - last_poll >= 1:
            last_poll = time.time()
            if step["check"](snapshot(), st.get("base") or {}):
                advance(i)
                continue
        try:
            k = getkey(timeout=0.5)
        except Exception:
            time.sleep(0.5); continue
        if k in ("\r", "\n"):
            if step.get("check"):
                waiting = True
                zj("hide-floating-panes")
            elif i < len(STEPS) - 1:
                advance(i)
            else:
                zj("hide-floating-panes")
        elif k in ("h", "H"):
            zj("hide-floating-panes")
        elif k in ("b", "B") and i:
            advance(i, i - 1)
        elif k in ("q", "Q"):
            advance(i, len(STEPS) - 1, show=False)
            zj("hide-floating-panes")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
