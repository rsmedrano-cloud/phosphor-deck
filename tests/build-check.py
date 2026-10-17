#!/usr/bin/env python3
"""Building a tab of cards, the whole way a newcomer walks it: + -> cards
-> pick -> Enter, and a new tab full of cards (kept, if asked); then an
existing tab: Alt-r -> r -> cards -> the preview -> Enter -> s keeps it.
And the "new here?" line the first pickers show, gone once learned.

    python3 tests/build-check.py           # the hint and the pickers, no zellij
    python3 tests/build-check.py --live    # and the whole path in a real one

--live runs a throwaway session (tests/zjprobe.py) with the deck's own
config and a client attached in a pty; without zellij it says so and passes.
"""
import io, json, os, re, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import zjprobe
from zjprobe import tap

PROFILE = '''
[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "SYS"
split = "rows"
panes = [
  { cmd = "sleep", args = ["601"], size = "55%" },
  { cmd = "sleep", args = ["602"] },
]

[[tabs]]
name  = "SH"
panes = [ { cmd = "" } ]
'''
ALT_E, ALT_N, ESC = b"\x1br", b"\x1bn", b"\x1b"
fails = []

def need(what, ok):
    if not ok:
        fails.append(what)
    return ok

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)

def pure():
    os.environ["PHOSPHOR_DATA"] = tempfile.mkdtemp(prefix="build-check-")
    import ui, edit
    got = [ui.first_times("gallery", "hi") for _ in range(ui.FIRST_TIMES + 2)]
    need("hint: the first times a picker opens, then never", got == ["hi"] * ui.FIRST_TIMES + [None, None])
    need("hint: each picker learns on its own", ui.first_times("pane", "hi") == "hi")
    open(os.path.join(os.environ["PHOSPHOR_DATA"], "hints.json"), "w").write("[")
    need("hint: a broken hints.json starts over, never stops a picker", ui.first_times("gallery", "hi") == "hi")

    items = [("btop", "a program"), ("cards", "the cards you pick")]
    real = shutil.get_terminal_size
    shutil.get_terminal_size = lambda d=None: os.terminal_size((80, 20))
    def screen(keys, hint):
        ks = iter(keys); edit.ui_getkey = lambda *a: next(ks)
        buf, out = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            got = edit.pick("what goes in this pane?", items, hint=hint)
        finally:
            sys.stdout = out
        return got, plain(buf.getvalue().split("\x1b[2J")[-1]).splitlines()
    got, lines = screen(["q"], "Enter: it runs here")
    need("pick: the hint on the last row", len(lines) == 20 and lines[-1] == " new here? Enter: it runs here")
    got, lines = screen(["q"], None)
    need("pick: no hint, no line", not any("new here?" in l for l in lines))
    got, _ = screen([("MOUSE", 0, 5, 5, True)], "Enter: it runs here")
    need("pick: with the hint, a tap still picks the row it's on", got == items[1])
    shutil.get_terminal_size = real

def live():
    if not zjprobe.zellij():
        print("no zellij here: live part skipped"); return
    with zjprobe.Probe(PROFILE) as z:
        prof = z.env["PHOSPHOR_PROFILE"]
        shown = lambda s: any(s in r for r in z.screen())
        z.pump(2)
        plus(z, prof, shown)
        existing(z, prof, shown)
        learned(z, shown)

def plus(z, prof, shown):
    """+ -> cards -> pick two -> Enter: a tab full of cards, kept."""
    z.action("go-to-tab-name", "SH"); z.pump(1)
    z.keys(ALT_N, 1)
    if not need("+: the menu offers cards", z.wait(lambda: shown("the cards you pick"), 10)): return
    tap(z, "keep this tab")
    need("+: keep this tab is ticked", z.wait(lambda: shown("[x] keep this tab"), 5))
    if not tap(z, "the cards you pick"): return
    if not need("+: cards opens the gallery", z.wait(lambda: shown("Enter: make the tab"), 10)): return
    need("+: the first time, it says what Space and Enter do",
         shown("new here? Space marks the cards you want"))
    need("+: the card under the cursor, as it'll look", shown("as it'll look"))
    z.keys(b" ", 0.5); z.keys(b"\x1b[B", 0.5); z.keys(b" ", 0.5)
    need("+: Space picks two", z.wait(lambda: shown("2 picked"), 5))
    z.keys(b"\r", 1)
    need("+: Enter opens a tab of cards", z.wait(lambda: "CARDS" in z.tabs(), 15))
    need("+: the tab is full of cards, two boxes",
         z.wait(lambda: "\n".join(z.screen()).count("╭─") >= 2, 20))
    need("+: kept: the profile has it as dash = [...]",
         z.wait(lambda: '"CARDS"' in open(prof).read() and "dash = [" in open(prof).read(), 10))
    need("the menu's tab closes behind it", z.wait(lambda: not any(t.startswith("Tab #") for t in z.tabs()), 5))

def existing(z, prof, shown):
    """An existing tab: Alt-r -> r -> cards -> preview -> Enter -> s keeps it."""
    tab = lambda: z.tabs()[0] if z.tabs() else ""
    z.action("go-to-tab-name", "SYS"); z.pump(1)
    z.keys(ALT_E, 1)
    if not need("edit: Alt-r asks to start", z.wait(lambda: shown("EDIT SYS"), 10)): return
    z.keys(b"\r", 1)
    need("edit: the tab unlocks", z.wait(lambda: tab() == "SYS ✎", 5))
    z.keys(ALT_E, 1)
    if not need("edit: Alt-r again offers r", z.wait(lambda: shown("what changed"), 10)): return
    z.keys(b"r", 1)
    if not need("edit: r asks what goes in this pane", z.wait(lambda: shown("what goes in this pane"), 10)): return
    need("edit: the first time, it says what Enter does", shown("new here? ↑↓ or a tap"))
    need("edit: and this pane's size beside the list", z.wait(lambda: re.search(r"\d+×\d+", "\n".join(z.screen())), 5))
    if not tap(z, "the cards you pick"): return
    if not need("edit: cards opens the gallery", z.wait(lambda: shown("Enter: put them here"), 10)): return
    need("edit: the preview at this pane's size", z.wait(lambda: shown("as it'll look") and shown("pane"), 5))
    z.keys(ESC, 1.5)
    need("edit: Esc in the gallery goes back to the list", z.wait(lambda: shown("what goes in this pane"), 5))
    if not tap(z, "the cards you pick"): return
    z.wait(lambda: shown("Enter: put them here"), 10)
    z.keys(b" ", 0.5); z.keys(b"\r", 1)
    need("edit: the pane becomes cards", z.wait(lambda: '"dash"' in z.action("dump-layout"), 15))
    need("edit: the old program is gone", z.wait(lambda: '"601"' not in z.action("dump-layout"), 10))
    z.keys(ALT_E, 1); z.wait(lambda: shown("what changed"), 10)
    z.keys(b"s", 1)
    need("edit: s keeps it as dash = [...] in SYS, the old program out",       # CARDS has the other one
         z.wait(lambda: open(prof).read().count("dash = [") == 2 and '"601"' not in open(prof).read(), 10))
    need("edit: saving locks the tab", z.wait(lambda: tab() == "SYS", 5))

def learned(z, shown):
    """Once it's been seen its few times, the gallery opens with no hint."""
    import ui
    data = os.path.join(z.home, ".local/share/phosphor/hints.json")
    seen = json.load(open(data)) if os.path.exists(data) else {}
    need("the gallery counted both opens", seen.get("gallery", 0) >= 2)
    seen["gallery"] = ui.FIRST_TIMES
    json.dump(seen, open(data, "w"))
    z.action("go-to-tab-name", "SH"); z.pump(1)
    z.keys(ALT_N, 1)
    if not tap(z, "the cards you pick"): return
    if not need("learned: the gallery opens", z.wait(lambda: shown("Enter: make the tab"), 10)): return
    need("learned: no hint any more", not shown("new here?"))
    z.keys(ESC, 1); z.keys(b"q", 1)

if __name__ == "__main__":
    pure()
    if "--live" in sys.argv:
        live()
    for f in fails:
        print("FAIL:", f)
    print("build-check:", "FAIL" if fails else "OK")
    sys.exit(1 if fails else 0)
