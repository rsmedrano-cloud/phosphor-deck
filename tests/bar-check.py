#!/usr/bin/env python3
"""The key bar ([bar], #100): one row under every tab, and a tap on a key
does what its Alt key does, on the pane you were in.

    python3 tests/bar-check.py

The row itself (pure): every width from 30 columns up holds every key and
the light, a narrow one shows only the words, a wide one the shortcuts; a
tap between keys goes to the nearer one; the input parser. gen puts the
bar in every template only with [bar] enabled; Alt-r never saves it.

Then a real zellij (zjprobe), two tabs: the bar is in both and works out
the light; with the focus on the right pane of a split, a tap on ASK asks
about that pane (its screen goes along), ZOOM zooms it, NOTE opens over
it, HOME goes to the first tab, and a tab whose last pane closes goes,
bar and all. At 40 columns the whole row still fits.
Needs zellij for that part; without it, it says so and checks the rest.
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import zjprobe
import bar

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

# ── the row ───────────────────────────────────────────────────
KEYS = {"home": "Alt-1", "ask": "Alt-q", "note": "Alt-j", "edit": "Alt-r", "zoom": "Alt-z"}
WORDS = [w for _, _, w in bar.KEYS]
for w in range(30, 201):
    for light in ("●", "● 12"):
        spans = bar.layout(w, KEYS, light)
        ids = [i for _, _, i, _ in spans]
        need("%d cols: every key and the light (%s)" % (w, ids), ids == [i for i, _, _ in bar.KEYS] + ["light"])
        need("%d cols: inside the row" % w, spans[0][0] >= 1 and spans[-1][1] <= w)
        need("%d cols: in order, apart" % w, all(a[1] < b[0] for a, b in zip(spans, spans[1:])))
row40 = " ".join(t for _, _, _, t in bar.layout(40, KEYS, "● 3"))
need("40 cols: only the words (%r)" % row40, all(w in row40 for w in WORDS) and "Alt" not in row40 and "⌂" not in row40)
row100 = " ".join(t for _, _, _, t in bar.layout(100, KEYS, "●"))
need("100 cols: glyphs and shortcuts (%r)" % row100, "⌂ HOME Alt-1" in row100 and "⤢ ZOOM Alt-z" in row100)
row100 = " ".join(t for _, _, _, t in bar.layout(100, {"home": "Alt-1"}, "●"))
need("a key that's off shows no shortcut (%r)" % row100, "? ASK" in row100 and "ASK Alt" not in row100)
spans = bar.layout(60, KEYS, "●")
need("a tap on a word is that key", all(bar.hit(spans, (a + b) // 2) == i for a, b, i, _ in spans))
need("a tap between two keys goes to the nearer", bar.hit(spans, spans[0][1]) == spans[0][2]
     and bar.hit(spans, spans[1][0] - 1) == spans[1][2])
need("a tap past the light is the light", bar.hit(spans, 59) == "light")
need("the light: count and color", bar.light_text({"status": "red", "problems": 2}) == ("● 2", bar.RED)
     and bar.light_text(None) == ("●", bar.DIM))

evs, rest = bar.events(b"\x1b[I\x1b[<0;12;1M\x1b[<0;12;1m\x1b[<64;3;1M\x1b[C\x1b[D\r\x1b[O\x1b[<0;5")
need("events: focus, a tap on release only, wheel ignored, keys (%r)" % evs,
     evs == [("focus", True), ("tap", 11), ("key", "right"), ("key", "left"), ("key", "enter"), ("focus", False)])
need("events: an unfinished sequence waits (%r)" % rest, rest == b"\x1b[<0;5")
need("events: Esc alone is held for the caller", bar.events(b"\x1b") == ([], b"\x1b"))
need("events: Esc then a key", bar.events(b"\x1bq")[0] == [("key", "esc"), ("key", "q")] or
     bar.events(b"\x1bq")[0] == [("key", "q")])

need("is_bar: by name, by command",
     bar.is_bar({"title": "BAR"}) and bar.is_bar({"terminal_command": "/x/phosphor bar"})
     and not bar.is_bar({"title": "SYS", "terminal_command": "/x/phosphor fleet"}))

# ── gen and keep ──────────────────────────────────────────────
import gen, keep
BASE = {"deck": {"session": "deck"}, "tabs": [{"name": "SYS", "panes": [{"cmd": "btop"}]}]}
off = gen.deck_kdl(BASE, gen.Ctx(BASE), "test")
need("without [bar] no bar", 'name="BAR"' not in off)
on_prof = dict(BASE, bar={"enabled": True})
on = gen.deck_kdl(on_prof, gen.Ctx(on_prof), "test")
need("with [bar]: in the template and the + menu's tab", on.count('name="BAR"') == 2)
need("with [bar]: under the panes", on.index("children") < on.index('name="BAR"'))
need("with [bar]: a tab's own layout too", 'name="BAR"' in gen.tab_kdl(BASE["tabs"][0], gen.Ctx(on_prof), "test"))
dumped = keep.parse('layout {\n  tab name="SYS" {\n    pane size=1 borderless=true {\n'
                    '      plugin location="zellij:tab-bar"\n    }\n    pane command="/x/phosphor" {\n      args "run" "--" "btop"\n    }\n'
                    '    pane size=1 borderless=true name="BAR" command="/x/phosphor" {\n      args "bar"\n    }\n  }\n}\n')
_, specs, _ = keep.tab_specs(dumped, "SYS", {"root": "/", "expand": lambda s: s, "cwd": "/", "tokens": []})
need("Alt-r never saves the bar into a tab (%r)" % specs, specs == [{"cmd": "btop"}])

# ── the phone kit's extra keys ────────────────────────────────
import phone
row_on, row_off = phone.keys_row(on_prof), phone.keys_row(BASE)
need("kit, bar on: EDIT leaves the extra keys; ZOOM (the way back: a zoom hides the bar) and EXIT stay (%s)" % row_on,
     "EDIT" not in row_on and '"ALT z", display: "ZOOM"' in row_on and '"ALT x", display: "EXIT"' in row_on
     and "ESC" in row_on)
need("kit, bar off: EDIT, ZOOM and EXIT", all(w in row_off for w in ("EDIT", "ZOOM", "EXIT")))
need("kit: a phone with the other row gets this one", row_off in phone.old_rows(on_prof) and row_on in phone.old_rows(BASE))
kit = phone.script(on_prof)
need("kit: says which keys it added", "say \"extra keys added: KEYBOARD, ZOOM, EXIT\"" in kit and "@KEYNAMES@" not in kit)

# ── a real zellij ─────────────────────────────────────────────
PROFILE = '''
[deck]
session = "barcheck"

[bar]
enabled = true

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "ONE"
split = "cols"
panes = [ { cmd = "" }, { cmd = "" } ]

[[tabs]]
name = "TWO"
panes = [ { cmd = "" } ]
'''

def all_panes(z):
    return [p for p in json.loads(z.action("list-panes", "-a", "-j") or "[]") if not p["is_plugin"]]

def active_tab(z):
    t = [t for t in json.loads(z.action("list-tabs", "-j") or "[]") if t.get("active")]
    return t[0] if t else {}

def bar_of(z):
    tid = active_tab(z).get("tab_id", active_tab(z).get("id"))
    return next((p for p in all_panes(z) if p["tab_id"] == tid and bar.is_bar(p)), None)

def bar_row(z):
    b = bar_of(z)
    if not b:
        return ""
    out = os.path.join(z.home, "bar.txt")
    z.action("dump-screen", "--pane-id", "terminal_%d" % b["id"], "--path", out)
    try:
        return (open(out).read().splitlines() or [""])[0]
    except OSError:
        return ""

def tap_key(z, word):
    """Tap the word on this tab's bar; True when it was there."""
    if not z.wait(lambda: word in bar_row(z), 10):
        return False
    b, col = bar_of(z), bar_row(z).find(word)
    x, y = b["pane_content_x"] + col + 2, b["pane_content_y"] + 1
    z.keys(b"\x1b[<0;%d;%dM" % (x, y), 0.1)
    z.keys(b"\x1b[<0;%d;%dm" % (x, y), 0.8)
    return True

def focused(z):
    tid = active_tab(z).get("tab_id")
    return next((p for p in all_panes(z) if p["tab_id"] == tid and p["is_focused"]), None)

def over_right(z, title, right):
    """The focused pane is `title`, where the right pane was (one look: it changes under us)."""
    f = focused(z) or {}
    return f.get("title") == title and f.get("pane_x") == right["pane_x"]

def shows(z, text, timeout=15):
    return z.wait(lambda: any(text in r for r in z.screen()), timeout)

if not zjprobe.zellij():
    print("  zellij isn't installed: the row, gen and keep only")
else:
    with zjprobe.Probe(PROFILE, session="barcheck", cols=100, rows=30) as z:
        got = os.path.join(z.home, "asked.txt")
        fake = os.path.join(z.home, ".local/bin/claude")
        open(fake, "w").write('#!/bin/sh\nprintf "%%s\\n" "$@" > %s\necho "THE ANSWER IS 42"\n' % got)
        os.chmod(fake, 0o755)
        need("the deck came up", z.wait(lambda: z.tabs()[:2] == ["ONE", "TWO"], 20))
        need("a bar in every tab", z.wait(lambda: sorted(p["tab_id"] for p in all_panes(z) if bar.is_bar(p))
                                          == sorted({p["tab_id"] for p in all_panes(z)}), 15))
        need("the bar shows the keys with their shortcuts (%r)" % bar_row(z),
             z.wait(lambda: "? ASK Alt-q" in bar_row(z) and "●" in bar_row(z), 15))
        status = os.path.join(z.home, ".cache/phosphor/bar-status.json")
        need("the light is worked out once, for every bar", z.wait(lambda: os.path.exists(status), 20))

        z.action("move-focus", "right"); z.pump(0.5)
        right = focused(z)
        z.keys("echo MAR''KER-$((6*7))\r", 1.0)
        need("the right pane shows the marker", shows(z, "MARKER-42"))

        need("ASK is on the bar", tap_key(z, "ASK"))
        need("a tap on ASK opens the ask over the pane you were in", shows(z, "phosphor ask"))
        cover = focused(z)
        need("ASK is focused, where the right pane was (%r)" % (cover and cover.get("title")),
             cover and cover.get("title") == "ASK" and cover["pane_x"] == right["pane_x"])
        z.wait(lambda: zjprobe.reading_keys(z, "--here"), 10)
        z.keys("what is this\r", 0.5)
        need("the answer shows", shows(z, "THE ANSWER IS 42"))
        sent = open(got).read() if os.path.exists(got) else ""
        need("the right pane's screen went along", "MARKER-42" in sent)
        z.keys("q", 0.5)
        need("q gives the right pane back", z.wait(lambda: (focused(z) or {}).get("id") == right["id"], 10))

        need("ZOOM is on the bar", tap_key(z, "ZOOM"))
        need("a tap on ZOOM zooms the pane you were in",
             z.wait(lambda: active_tab(z).get("is_fullscreen_active") and (focused(z) or {}).get("id") == right["id"], 10))
        need("a zoom covers the bar (ZOOM stays on the phone's extra keys for that)",
             next(p for p in all_panes(z) if p["id"] == right["id"])["pane_rows"] > right["pane_rows"]
             and int(active_tab(z).get("panes_to_hide", 0)) >= 1)
        z.action("toggle-fullscreen"); z.pump(0.5)

        need("NOTE is on the bar", z.wait(lambda: not active_tab(z).get("is_fullscreen_active"), 5) and tap_key(z, "NOTE"))
        need("a tap on NOTE opens over the pane you were in",
             z.wait(lambda: over_right(z, "NOTE", right), 10))
        z.action("close-pane"); z.pump(0.5)

        z.action("go-to-tab", "2"); z.pump(0.5)
        need("HOME is on the second tab's bar", tap_key(z, "HOME"))
        need("a tap on HOME goes to the first tab", z.wait(lambda: active_tab(z).get("position") == 0, 10))

        z.action("go-to-tab", "2"); z.pump(0.5)
        z.wait(lambda: active_tab(z).get("position") == 1, 5)
        z.action("close-pane"); z.pump(0.5)
        need("a tab whose last pane closed goes, bar and all (%r)" % z.tabs(),
             z.wait(lambda: z.tabs() == ["ONE"], 10))

        # last: editing marks the tab's name
        need("EDIT is on the bar", tap_key(z, "EDIT"))
        need("a tap on EDIT edits the tab, over the pane you were in",
             z.wait(lambda: over_right(z, "EDIT", right), 10))

    with zjprobe.Probe(PROFILE, session="barnarrow", cols=40, rows=16) as z:
        need("40 cols: the deck came up", z.wait(lambda: "ONE" in z.tabs(), 20))
        need("40 cols: every key and the light on one row (%r)" % bar_row(z),
             z.wait(lambda: all(w in bar_row(z) for w in WORDS) and "●" in bar_row(z), 15))

if fails:
    print("bar-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("bar-check ok")
