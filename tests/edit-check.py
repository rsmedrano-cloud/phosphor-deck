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

def main():
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
        if not need("the tab is marked while editing", z.wait(lambda: tab() == "SYS ✎", 5)): return
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
        z.keys(ALT_E, 1); z.wait(lambda: "EDIT SYS" in z.text(), 5); z.keys(b"\r", 1)
        z.wait(lambda: tab() == "SYS ✎", 5)
        z.keys(CTRL_N, 0.3); z.keys(b"k", 0.3); z.keys(b"k", 0.3); z.keys(b"k", 0.3); z.keys(ESC, 0.5)
        z.wait(lambda: sizes() != saved, 5)
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        z.keys(b"d", 1)
        need("d puts the tab back as the profile has it",
             z.wait(lambda: sizes() == saved and z.tabs() == ["SYS", "SH"], 15))
        need("putting back leaves the profile alone", edited[0] in open(prof).read())

        # 3. swap the program of the focused pane, then save
        items = z.py("import edit\nfor i in edit.options(): print(i[0])").splitlines()
        idx = items.index("mytool")
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "EDIT SYS" in z.text(), 5); z.keys(b"\r", 1)
        z.wait(lambda: tab() == "SYS ✎", 5)
        z.out = b""
        z.keys(ALT_E, 1); z.wait(lambda: "what changed" in z.text(), 10)
        z.keys(b"r", 1); z.wait(lambda: "what goes in this pane" in z.text(), 5)
        for _ in range(idx): z.keys(b"j", 0.15)
        z.keys(b"\r", 1)
        need("r swaps the pane's program", z.wait(lambda: '"903"' in z.action("dump-layout"), 15))
        need("the swapped-out program is gone",
             z.wait(lambda: not any("sleep 601" in open("/proc/%s/cmdline" % d).read().replace("\0", " ")
                                    for d in os.listdir("/proc") if d.isdigit() and os.path.exists("/proc/%s/cmdline" % d)
                                    and z.home.encode() in _env(d)), 10))
        z.out = b""
        z.keys(ALT_E, 1)
        need("the swap shows as a change", z.wait(lambda: "sleep 601 → sleep 903" in z.text(), 10))
        z.keys(b"s", 1)
        need("s saves the swapped program", z.wait(lambda: '"903"' in open(prof).read() and '"601"' not in open(prof).read(), 10))

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

def tap(z, label, timeout=10):
    """Tap the row of the focused pane that shows this text."""
    import json
    out = os.path.join(z.home, "screen.txt")
    end = time.time() + timeout
    while time.time() < end:
        try: os.remove(out)
        except OSError: pass
        z.action("dump-screen", "--path", out)
        rows = open(out).read().splitlines() if os.path.exists(out) else []
        hit = [i for i, r in enumerate(rows) if label in r]
        active = [t for t in json.loads(z.action("list-tabs", "-s", "-j") or "[]") if t.get("active")]
        tab_id = active[0].get("tab_id", active[0].get("id")) if active else None
        me = [p for p in json.loads(z.action("list-panes", "-a", "-j")) if p["is_focused"] and not p["is_plugin"]
              and not p["is_suppressed"] and p["tab_id"] == tab_id]     # every tab has a focused pane
        if hit and me:
            x, y = me[0]["pane_content_x"] + 4, me[0]["pane_content_y"] + hit[0] + 1
            z.keys(b"\x1b[<0;%d;%dM" % (x, y), 0.1); z.keys(b"\x1b[<0;%d;%dm" % (x, y), 0.8)
            return True
        z.pump(0.3)
    return False

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
    if not need("touch: the tab unlocks", z.wait(lambda: tab() == "SYS ✎", 5)): return
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
         z.wait(lambda: "MYTOOL" in z.tabs() and body().count('"903"') >= 3, 10))   # the SYS pane + two new
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

def _env(d):
    try: return open("/proc/%s/environ" % d, "rb").read()
    except OSError: return b""

if __name__ == "__main__":
    rc = main()
    if zjprobe.zellij(): own_keys()
    if fails:
        print("failed: " + "; ".join(fails)); sys.exit(1)
    sys.exit(rc or 0)
