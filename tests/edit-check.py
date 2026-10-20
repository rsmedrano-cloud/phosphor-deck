#!/usr/bin/env python3
"""Alt-r in a real zellij: unlock a tab, resize it, save it; put it back;
swap a pane's program; and all of it again with taps only (a phone's EDIT
key sends the same Alt-r).

    python3 tests/edit-check.py

Runs a throwaway session (tests/zjprobe.py) with the deck's own config and a
client attached in a pty. Needs zellij; without it, it says so and passes.
"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zjprobe

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
ALT_E, CTRL_N, ESC = b"\x1br", b"\x0e", b"\x1b"
fails = []

def need(what, ok):
    if not ok:
        fails.append(what)
    return ok

def pure():
    """No zellij needed: what d can put back, what r and the layout offer."""
    import tempfile
    tmp = tempfile.mkdtemp()
    env0 = dict(os.environ)
    prof = os.path.join(tmp, "deck.toml")
    os.environ.update(HOME=tmp, PHOSPHOR_PROFILE=prof, PATH=os.path.join(tmp, ".local/bin") + ":/usr/bin:/bin")
    td = os.path.join(tmp, ".config/phosphor/tabs.d"); os.makedirs(td)
    open(prof, "w").write(PROFILE + '\n[[hosts]]\nname = "db-box"\nrole = "work"\nssh = "db-box"\n')
    open(os.path.join(td, "bubble.toml"), "w").write('[[tabs]]\nname = "BUBBLE"\npanes = [ { cmd = "" } ]\n')
    bin_ = os.path.join(tmp, ".local/bin"); os.makedirs(bin_)
    for b in ("btop", "gping"):
        open(os.path.join(bin_, b), "w").write("#!/bin/sh\n"); os.chmod(os.path.join(bin_, b), 0o755)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
    import edit
    # c over a pane: a row of cards is read back from its command line
    need("dash_of: a profile tab's row", edit.dash_of(
        ["/usr/bin/python3", "/x/phosphor", "run", "--name", "CARDS", "--", "/usr/bin/python3", "/x/phosphor",
         "dash", "--tab", "SYS", "version", "screens"]) == ("CARDS", "SYS", ["version", "screens"]))
    need("dash_of: one opened by hand", edit.dash_of(["phosphor", "dash", "ci"]) == ("CARDS", None, ["ci"]))
    need("dash_of: anything else isn't one", edit.dash_of(["sleep", "601"]) is None and edit.dash_of(None) is None)
    need("a profile tab can be put back", edit.origin("SYS") == (True, None))
    need("a tabs.d tab can be put back too (gen wrote its layout)",
         edit.origin("BUBBLE")[1] and edit.origin("BUBBLE")[1].endswith("bubble.toml"))
    need("a tab opened with + has nothing to go back to", edit.origin("NEWONE") == (False, None))
    opts = {i[0]: i for i in edit.options()}
    g = opts.get("gping")
    need("r offers gping with the fleet's hosts, not bare (it exits with none)",
         g and "db-box" in g[3][1:] and g[4].get("args") == ["@hosts"])
    need("r offers btop", "btop" in opts)
    import dash
    got = [["ci", "web"], None]
    dash.gallery = lambda have, **k: got.pop(0)
    it = edit.cards(opts["cards"])
    need("cards: the gallery's picks go in the pane", it[3][1:] == ["dash", "ci", "web"] and it[4] == {"dash": ["ci", "web"]})
    need("cards: Esc in the gallery puts nothing there", edit.cards(opts["cards"]) is None)
    need("cards: a program goes in as it is", edit.cards(opts["btop"]) == opts["btop"])
    asked = []
    dash.gallery = lambda have, **k: asked.append(k.get("cell"))
    edit.cards(opts["cards"], (59, 18))
    need("cards: the gallery previews at the pane's size", asked == [(59, 18)])
    previews(edit, opts)
    os.environ.clear(); os.environ.update(env0)

def previews(edit, opts):
    """A preview before you place it: real cell sizes, the shape's map,
    the list with the preview beside or under it, the layout asking the
    gallery for its pane's size."""
    import io, shutil, newtab, preview
    plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
    quad = {"split": "cols", "panes": [{"split": "rows", "panes": [0, 1]}, {"split": "rows", "panes": [2, 3]}]}
    c = preview.cells(quad, 122, 40)
    need("cells: a 2 x 2 tab in four equal parts", c == {0: (0, 0, 61, 20), 1: (0, 20, 61, 20),
                                                        2: (61, 0, 61, 20), 3: (61, 20, 61, 20)})
    need("cells: three columns cover the tab", sum(v[2] for v in preview.cells(
        {"split": "cols", "panes": [0, 1, 2]}, 100, 30).values()) == 100)
    need("inside: a cell less its frame", preview.inside(quad, 1, (122, 40)) == (59, 18))
    m = [plain(l) for l in preview.shape_map(quad, {0: "lazydocker", 1: "btop"}, 1, 32, 10, (122, 40))]
    need("map: as wide as asked, the tab's proportions", all(len(l) == 32 for l in m) and len(m) == 10)
    need("map: what's in each pane so far, this one's real size",
         "lazydocker" in m[1] and "btop" in m[6] and "59×18" in m[7])
    real = shutil.get_terminal_size
    items = [opts["btop"], opts["cards"]]
    side = lambda it, w, h: ["SIDE " + it[0]]
    def screen(size, keys):
        shutil.get_terminal_size = lambda d=None: os.terminal_size(size)
        ks = iter(keys); edit.ui_getkey = lambda *a: next(ks)
        buf, out = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            got = edit.pick("pane 2 of 4: what goes here?", items, (), side)
        finally:
            sys.stdout = out
        return got, plain(buf.getvalue().split("\x1b[2J")[-1]).splitlines()
    got, lines = screen((100, 24), ["j", "q"])
    need("pick: the preview beside the list, for the one under the cursor",
         any("cards" in l and "SIDE cards" not in l for l in lines) and
         any(l.index("SIDE cards") > edit.LIST_W for l in lines if "SIDE cards" in l))
    got, lines = screen((50, 30), ["q"])
    need("pick: under the list on a narrow screen", lines and "SIDE btop" in lines[-1])
    got, _ = screen((100, 24), [("MOUSE", 0, 80, 4, True), ("MOUSE", 0, 5, 4, True)])
    need("pick: a tap on the preview picks nothing, one on the list does", got == opts["btop"])
    picks, cells = [("2 × 2", ""), opts["cards"], None], []
    edit.pick = lambda *a, **k: picks.pop(0)
    edit.cards = lambda it, cell=None: cells.append(cell)
    preview.tab_size = lambda: (122, 40)
    newtab.layout({}, False)
    need("layout: cards in pane 1 are previewed at its real size", cells == [(59, 18)])
    shutil.get_terminal_size = real

def main():
    pure()
    if not zjprobe.zellij():
        print("no zellij here: skipped"); return 0
    with zjprobe.Probe(PROFILE) as z:
        prof = z.env["PHOSPHOR_PROFILE"]
        apps = os.path.join(z.home, ".config/phosphor/apps.toml")
        open(apps, "w").write('[[apps]]\nname = "mytool"\ncmd = "sleep"\nargs = ["903"]\n')
        tab = lambda: z.tabs()[0] if z.tabs() else ""
        sizes = lambda: re.findall(r'size="(\d+%)"', z.action("dump-layout").split("new_tab_template")[0])
        z.pump(2)

        # 1. unlock, resize, save
        z.keys(ALT_E, 1)
        if not need("Alt-r shows the edit screen", z.wait(lambda: "EDIT SYS" in z.text(), 10)): return
        z.keys(b"\r", 1)
        if not need("the tab is marked while editing", z.wait(lambda: tab().startswith("SYS ✎"), 5)): return
        start = sizes()
        z.keys(CTRL_N, 0.3); z.keys(b"j", 0.3); z.keys(b"j", 0.3); z.keys(ESC, 0.5)
        if not need("resizing works while editing", z.wait(lambda: sizes() != start, 5)): return
        edited = sizes()
        z.out = b""
        z.keys(ALT_E, 1)
        need("Alt-r again shows what changed", z.wait(lambda: "what changed" in z.text() and "→" in z.text(), 10))
        z.keys(b"s", 1)
        need("s saves the new size", z.wait(lambda: edited[0] in open(prof).read(), 10))
        need("saving locks and unmarks the tab", z.wait(lambda: tab() == "SYS", 5))

        # 2. unlock, resize, put it back
        saved = sizes()
        before = len(sleeps(z))
        z.keys(ALT_E, 1); z.wait(lambda: "EDIT SYS" in z.text(), 5); z.keys(b"\r", 1)
        z.wait(lambda: tab().startswith("SYS ✎"), 5)
        z.keys(CTRL_N, 0.3); z.keys(b"k", 0.3); z.keys(b"k", 0.3); z.keys(b"k", 0.3); z.keys(ESC, 0.5)
        z.wait(lambda: sizes() != saved, 5)
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        z.keys(b"d", 1)
        need("d puts the tab back as the profile has it",
             z.wait(lambda: sizes() == saved and z.tabs() == ["SYS", "SH"], 15))
        need("putting back leaves the profile alone", edited[0] in open(prof).read())
        need("putting back leaves nothing of the old tab running", z.wait(lambda: len(sleeps(z)) == before, 10))

        # 3. swap the program of the focused pane, then save
        items = z.py("import edit\nfor i in edit.options(): print(i[0])").splitlines()
        idx = items.index("mytool")
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "EDIT SYS" in z.text(), 5); z.keys(b"\r", 1)
        z.wait(lambda: tab().startswith("SYS ✎"), 5)
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        z.keys(b"r", 1); z.wait(lambda: "what goes in this pane" in z.text(), 5)
        for _ in range(idx): z.keys(b"j", 0.15)
        z.keys(b"\r", 1)
        need("r swaps the pane's program", z.wait(lambda: '"903"' in z.action("dump-layout"), 15))
        need("the swapped-out program is gone", z.wait(lambda: not sleeps(z), 10))
        z.out = b""
        z.keys(ALT_E, 1)
        need("the swap shows as a change", z.wait(lambda: "sleep 601 → sleep 903" in z.text(), 10))
        z.keys(b"s", 1)
        need("s saves the swapped program", z.wait(lambda: '"903"' in open(prof).read() and '"601"' not in open(prof).read(), 10))

        # 3b. c: a row of cards under the pane, picked in the gallery, then saved
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "EDIT SYS" in z.text(), 5); z.keys(b"\r", 1)
        z.wait(lambda: tab().startswith("SYS ✎"), 5)
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        need("c offers a row of cards", "add a row of cards" in z.text())
        z.keys(b"c", 1); z.wait(lambda: "put them under this pane" in z.text(), 10)
        z.keys(b" ", 0.5); z.keys(b"\r", 1)
        need("c puts a row of cards under the pane", z.wait(lambda: "dash" in z.action("dump-layout"), 15))
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        z.keys(b"s", 1)
        need("s keeps the row of cards in the profile", z.wait(lambda: "dash = [" in open(prof).read(), 10))

        # 4. taps only
        touch(z, prof)

        # 5. Alt-n: a new tab in the folder of the pane you're in; Alt-← crosses tabs
        here(z)

        # 6. + → layout: a shape, then what goes in each pane (taps only)
        shapes(z)

        # 7. Alt-j: a todo from the tab you're in, tagged with it (taps only)
        jot(z)

        # 8. closing a kept tab's last program offers to forget it
        forget(z)

tap = zjprobe.tap

def drag(z, row0, row1, col=60):
    z.keys(b"\x1b[<0;%d;%dM" % (col, row0 + 1), 0.2)
    for r in range(row0 + 1, row1 + 1):
        z.keys(b"\x1b[<32;%d;%dM" % (col, r + 1), 0.1)
    z.keys(b"\x1b[<0;%d;%dm" % (col, row1 + 1), 0.8)

def touch(z, prof):
    """The same edit, with taps and a drag only."""
    import json
    tab = lambda: z.tabs()[0] if z.tabs() else ""
    count = lambda: len([p for p in json.loads(z.action("list-panes", "-a", "-j"))
                         if not p["is_plugin"] and not p["is_suppressed"]])
    z.keys(ALT_E, 1)
    if not need("touch: start editing is a row to tap", tap(z, "start editing")): return
    if not need("touch: the tab unlocks", z.wait(lambda: tab().startswith("SYS ✎"), 5)): return
    z.action("move-focus", "up")
    geo = sorted((p["pane_y"], p["pane_rows"]) for p in json.loads(z.action("list-panes", "-a", "-j"))
                 if not p["is_plugin"] and not p["is_suppressed"])
    border = geo[0][0] + geo[0][1]
    before = open(prof).read()
    drag(z, border, border - 4)
    n = count()
    z.keys(ALT_E, 1)
    if not need("touch: split is a row to tap", tap(z, "a new pane below")): return
    need("touch: split adds a pane", z.wait(lambda: count() == n + 1, 10))
    z.keys(ALT_E, 1)
    if not need("touch: close is a row to tap", tap(z, "close this pane")): return
    need("touch: close takes the new pane away", z.wait(lambda: count() == n, 10))
    z.keys(ALT_E, 1)
    if not need("touch: save is a row to tap", tap(z, "save into the profile")): return
    need("touch: the dragged size is saved", z.wait(lambda: open(prof).read() != before, 10))
    need("touch: saving locks the tab", z.wait(lambda: tab() == "SYS", 5))

def here(z):
    import json
    focused = lambda: [p["tab_name"] for p in json.loads(z.action("list-panes", "-a", "-j"))
                       if p["is_focused"] and not p["is_plugin"] and not p["is_suppressed"]]
    z.action("go-to-tab-name", "SH"); z.pump(1)
    os.makedirs(os.path.join(z.home, "proj/sub"), exist_ok=True)
    z.keys(b"cd proj/sub\r", 1)
    z.keys(b"\x1bn", 1)
    def menu_cwd():
        for d in os.listdir("/proc"):
            try:
                if " new" in open("/proc/%s/cmdline" % d).read().replace("\0", " ") and \
                   "--here" not in open("/proc/%s/cmdline" % d).read() and z.home.encode() in _env(d):
                    return os.readlink("/proc/%s/cwd" % d)
            except OSError:
                pass
    need("Alt-n opens the menu in the pane's folder",
         z.wait(lambda: menu_cwd() == os.path.join(z.home, "proj/sub"), 10))
    z.keys(b"q", 1)
    z.action("go-to-tab-name", "SH"); z.pump(1)
    z.keys(b"\x1b[1;3D", 1)
    need("Alt-← past the last pane goes to the tab before", z.wait(lambda: focused() and focused()[0].startswith("SYS"), 5))

def shapes(z):
    z.action("go-to-tab-name", "SH"); z.pump(1)
    z.keys(b"\x1bn", 1)
    if not need("layout is in the + menu", tap(z, "several panes at once")): return
    if not need("shapes to tap", tap(z, "2 columns")): return
    if not need("pane 1: pick a program", tap(z, "mytool")): return
    if not need("pane 2: the same in the rest", tap(z, "the same in the rest")): return
    body = lambda: z.action("dump-layout").split("new_tab_template")[0]
    need("the layout opens as a tab with both panes",
         z.wait(lambda: "MYTOOL" in z.tabs() and body().count('"903"') >= 2, 10))
    z.keys(b"\x1bn", 1)
    tap(z, "several panes at once"); tap(z, "2 rows")
    tap(z, "mytool")
    if not need("grid: cards is a row to tap", tap(z, "the cards you pick")): return
    if not need("grid: the gallery opens", z.wait(lambda: "Enter: put them here" in z.text(), 10)): return
    z.keys(b" ", 0.5); z.keys(b"\r", 1)
    need("grid: a program and cards side by side",
         z.wait(lambda: "LAYOUT" in z.tabs() and '"dash"' in body(), 10))
    need("the menu's tab closes behind it", z.wait(lambda: not any(t.startswith("Tab #") for t in z.tabs()), 5))

def jot(z):
    book = os.path.join(z.home, ".local/share/phosphor/notes.md")
    z.action("go-to-tab-name", "SYS"); z.pump(1)
    z.keys(b"\x1bj", 1)
    if not need("Alt-j asks for a note", z.wait(lambda: "a note" in z.text(), 10)): return
    if not need("jot: todo is a row to tap", tap(z, "todo")): return
    z.wait(lambda: "new todo" in z.text(), 5)
    z.keys(b"disk almost full\r", 0.5); z.keys(b"\r", 2)
    need("jot: saved with the tab it came from",
         z.wait(lambda: os.path.exists(book) and "todo · " in open(book).read()
                and "@SYS · disk almost full" in open(book).read(), 10))
    need("jot: the screen closes over the pane", z.wait(lambda: 'name="NOTE"' not in z.action("dump-layout"), 10))

def forget(z):
    prof = z.env["PHOSPHOR_PROFILE"]
    need("SH starts in the profile", 'name  = "SH"' in open(prof).read())
    z.action("go-to-tab-name", "SH"); z.pump(1)
    z.keys(b"exit\r", 2)
    if not need("a kept tab offers to forget it", tap(z, "close it and forget it")): return
    need("forget closes the tab", z.wait(lambda: "SH" not in z.tabs(), 10))
    need("forget takes it out of the profile", z.wait(lambda: '"SH"' not in open(prof).read(), 10))
    need("the other tabs stay", '"SYS"' in open(prof).read())

def own_keys():
    """[keys] in the profile moves the deck's keys, and phosphor shortcuts
    changes one live: the new key works without a restart."""
    import json
    prof = PROFILE.replace('[[tabs]]\nname  = "SYS"', '[keys]\nedit = "Alt y"\n\n[[tabs]]\nname  = "SYS"', 1)
    with zjprobe.Probe(prof) as z:
        z.pump(2)
        z.keys(b"\x1br", 1.5)
        need("own keys: the default edit key is free", "EDIT SYS" not in z.text())
        z.keys(b"\x1by", 1)
        need("own keys: [keys] edit opens the edit screen", z.wait(lambda: "EDIT SYS" in z.text(), 10))
        z.keys(b"q", 1)
        z.action("go-to-tab-name", "SH"); z.pump(1)
        z.keys(b"$HOME/.local/bin/phosphor shortcuts\r", 2)   # a login shell here has no ~/.local/bin in PATH
        if not need("shortcuts: the list", tap(z, "zoom: the focused pane")): return
        z.wait(lambda: "press the new key" in z.text(), 5)
        z.keys(b"\x1bu", 2)
        need("shortcuts: saved into the profile",
             z.wait(lambda: 'zoom' in open(z.env["PHOSPHOR_PROFILE"]).read() and '"Alt u"' in open(z.env["PHOSPHOR_PROFILE"]).read(), 10))
        need("shortcuts: gen wrote it into config.kdl", z.wait(lambda: 'bind "Alt u" { ToggleFocusFullscreen; }' in open(z.config).read(), 10))
        z.keys(b"q", 1)
        full = lambda: any(t.get("is_fullscreen_active") for t in json.loads(z.action("list-tabs", "-s", "-j")) if t.get("active"))
        z.action("go-to-tab-name", "SYS"); z.pump(2)
        z.keys(b"\x1bu", 1.5)
        need("shortcuts: the new key works without a restart", z.wait(full, 8))

def sleeps(z):
    """This probe's `sleep 601` processes."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try:
            if "sleep 601" in open("/proc/%s/cmdline" % d).read().replace("\0", " ") and z.home.encode() in _env(d):
                out.append(d)
        except OSError:
            pass
    return out

def _env(d):
    try: return open("/proc/%s/environ" % d, "rb").read()
    except OSError: return b""

if __name__ == "__main__":
    rc = main()
    if zjprobe.zellij(): own_keys()
    if fails:
        print("failed: " + "; ".join(fails)); sys.exit(1)
    sys.exit(rc or 0)
