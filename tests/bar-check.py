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
WORDS = [w for i, _, w in bar.KEYS if i != "mic"]      # the probe has no voice: no MIC
# without MIC (voice off) from 30 columns, with it from 34
NOMIC = [k for k in bar.KEYS if k[0] != "mic"]
for keyset, least in ((NOMIC, 30), (bar.KEYS, 34)):
  for w in range(least, 201):
    for light in (("●", ""), ("●", "12")):
        spans = bar.layout(w, dict(KEYS, mic="Alt-m"), light, ids=keyset)
        ids = [s[2] for s in spans]
        need("%d cols: every key and the light (%s)" % (w, ids), ids == [i for i, _, _ in keyset] + ["light"])
        need("%d cols: inside the row" % w, spans[0][0] >= 1 and spans[-1][1] <= w)
        need("%d cols: in order, apart" % w, all(a[1] < b[0] for a, b in zip(spans, spans[1:])))
        need("%d cols: each cell holds both its rows" % w,
             all(max(len(s[3]), len(s[4])) == s[1] - s[0] for s in spans))
cell = lambda spans, i: next(s[3:] for s in spans if s[2] == i)
s40 = bar.layout(40, KEYS, ("●", "3"))
need("40 cols: the glyph over the word, no shortcut (%r)" % s40,
     cell(s40, "home") == ("⌂", "HOME") and all("Alt" not in s[3] for s in s40) and cell(s40, "light") == ("●", "3"))
s100 = bar.layout(100, KEYS, ("●", ""))
need("100 cols: the glyph and shortcut over the word (%r)" % s100,
     cell(s100, "home") == ("⌂ Alt-1", "HOME") and cell(s100, "zoom") == ("⤢ Alt-z", "ZOOM"))
need("a key that's off shows no shortcut", cell(bar.layout(100, {"home": "Alt-1"}, ("●", "")), "ask") == ("?", "ASK"))
one = bar.layout(60, KEYS, ("●", "2"), rows=1)
need("on one row (an older layout) only the words, the light beside its count (%r)" % one,
     all(s[3] == "" for s in one) and cell(one, "light") == ("", "● 2") and cell(one, "ask") == ("", "ASK"))
import re
plain = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
_, lines = bar.draw(60, KEYS, {"status": "red", "problems": 2}, sel="ask")
need("draw: two rows, glyphs over words (%r)" % [plain(l) for l in lines],
     len(lines) == 2 and "? Alt-q" in plain(lines[0]) and " ASK " in plain(lines[1]) and "2" in plain(lines[1]))
need("draw: the selected key in reverse on both rows", all("\x1b[7m" in l for l in lines))
spans = bar.layout(60, KEYS, ("●", ""))
need("a tap on a key is that key", all(bar.hit(spans, (a + b) // 2) == i for a, b, i, *_ in spans))
need("a tap between two keys goes to the nearer", bar.hit(spans, spans[0][1]) == spans[0][2]
     and bar.hit(spans, spans[1][0] - 1) == spans[1][2])
need("a tap past the light is the light", bar.hit(spans, 59) == "light")
need("the light: count and color", bar.light_text({"status": "red", "problems": 2}) == ("●", "2", bar.RED)
     and bar.light_text(None) == ("●", "", bar.DIM))

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
need("with [bar]: two rows tall (#111)", 'pane size=2 borderless=true name="BAR"' in on)
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

def bar_rows(z, b=None):
    """The bar's two rows: glyphs (and shortcuts), then words."""
    b = b or bar_of(z)
    if not b:
        return ["", ""]
    out = os.path.join(z.home, "bar.txt")
    z.action("dump-screen", "--pane-id", "terminal_%d" % b["id"], "--path", out)
    try:
        return (open(out).read().splitlines() + ["", ""])[:2]
    except OSError:
        return ["", ""]

def bar_row(z):
    return bar_rows(z)[1]

def tap_key(z, word, row=1):
    """Tap the word's key on this tab's bar, on its word's row (1) or its
    glyph's (0); True when it was there."""
    # the bar and its rows read together: under load a second list-panes
    # can come back empty between them (release 2.8.15's check.sh)
    seen = {}
    def found():
        b = bar_of(z)
        rows = bar_rows(z, b) if b else ["", ""]
        if any(word in r for r in rows):
            seen.update(b=b, rows=rows)
            return True
        return False
    if not z.wait(found, 10):
        return False
    b, col = seen["b"], max(r.find(word) for r in seen["rows"])
    x, y = b["pane_content_x"] + col + 2, b["pane_content_y"] + 1 + row
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

def over_it(z, title, right):
    """The focused pane is `title`, the right pane hidden under it: Alt-r's
    map widens itself to the whole tab (#125), so not at the right pane's place."""
    f = focused(z) or {}
    under = [p for p in json.loads(z.action("list-panes", "-a", "-j") or "[]") if p["id"] == right["id"] and not p["is_plugin"]]
    return f.get("title") == title and under and under[0]["is_suppressed"]

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
        need("the bar shows the keys, their shortcuts over their words (%r)" % bar_rows(z),
             z.wait(lambda: "? Alt-q" in bar_rows(z)[0] and "●" in bar_rows(z)[0] and " ASK " in bar_row(z), 15))
        status = os.path.join(z.home, ".cache/phosphor/bar-status.json")
        need("the light is worked out once, for every bar", z.wait(lambda: os.path.exists(status), 20))

        z.action("move-focus", "right"); z.pump(0.5)
        right = focused(z)
        z.keys("echo MAR''KER-$((6*7))\r", 1.0)
        need("the right pane shows the marker", shows(z, "MARKER-42"))

        need("ASK is on the bar", tap_key(z, "ASK"))
        need("a tap on ASK opens the ask over the pane you were in", shows(z, "phosphor ask"))
        back = "Esc: back to %s (still running)" % right["title"]
        need("ASK says how to get back to the pane (#110)", shows(z, back))
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

        # #110: the light opens glance over the pane; it says how to get back, Esc does
        z.keys("sleep 300; echo SL''EPT\r", 0.5)
        z.wait(lambda: any("sleep 300" in r for r in z.screen()), 5)   # the pane has it, and the focus
        need("the light is on the bar", tap_key(z, "●", row=0))
        opened = z.wait(lambda: over_right(z, "GLANCE", right), 10)
        need("a tap on the light opens glance over the pane you were in (focused: %r; glance panes: %r)"
             % ({k: (focused(z) or {}).get(k) for k in ("title", "pane_x")},
                [(p["title"], p["pane_x"], p["exited"]) for p in all_panes(z) if p["title"] == "GLANCE"]), opened)
        need("glance names the pane under it, still running (%r)" % z.screen()[:2], shows(z, back))
        z.keys("\x1b", 1.0)
        need("Esc gives the pane back", z.wait(lambda: (focused(z) or {}).get("id") == right["id"], 10))
        need("what ran there still runs", not any("SLEPT" in r for r in z.screen()))
        z.keys("\x03", 0.5); z.keys("echo AG''AIN-$((1+1))\r", 1.0)
        need("and the pane still answers", shows(z, "AGAIN-2"))

        need("ZOOM is on the bar (a tap on its glyph)", tap_key(z, "ZOOM", row=0))
        need("a tap on ZOOM zooms the pane you were in",
             z.wait(lambda: active_tab(z).get("is_fullscreen_active") and (focused(z) or {}).get("id") == right["id"], 10))
        need("a zoom covers the bar (ZOOM stays on the phone's extra keys for that)",
             next(p for p in all_panes(z) if p["id"] == right["id"])["pane_rows"] > right["pane_rows"]
             and int(active_tab(z).get("panes_to_hide", 0)) >= 1)
        z.action("toggle-fullscreen"); z.pump(0.5)

        need("NOTE is on the bar", z.wait(lambda: not active_tab(z).get("is_fullscreen_active"), 5) and tap_key(z, "NOTE"))
        need("a tap on NOTE opens over the pane you were in",
             z.wait(lambda: over_right(z, "NOTE", right), 10))
        need("NOTE says how to get back to the pane", shows(z, back))
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
             z.wait(lambda: over_it(z, "EDIT", right), 10))
        need("EDIT says how to get back to the pane", shows(z, back))
        need("EDIT's map starts on the pane you were in (the right one)", shows(z, "▶ 2 "))

    with zjprobe.Probe(PROFILE, session="barnarrow", cols=40, rows=16) as z:
        need("40 cols: the deck came up", z.wait(lambda: "ONE" in z.tabs(), 20))
        need("40 cols: every key and the light (%r)" % bar_rows(z),
             z.wait(lambda: all(w in bar_row(z) for w in WORDS) and "●" in bar_rows(z)[0], 15))

    # #111: the pane over the bar keeps its last line, and the line between
    # them stays put, on the whole screen (zellij's own drawing, not a pane's)
    import vt
    LONG = PROFILE.split("[[tabs]]")[0] + '''
[[tabs]]
name = "LONG"
panes = [ { cmd = "sh", args = ["-c", "i=0; while :; do i=$((i+1)); echo line $i; sleep 0.2; done"] } ]
'''
    with zjprobe.Probe(LONG, session="barlines", cols=80, rows=20) as z:
        need("lines: the deck came up", z.wait(lambda: "LONG" in z.tabs(), 20))
        need("lines: the bar is up", z.wait(lambda: bar_of(z) is not None and "HOME" in bar_row(z), 15))
        b = bar_of(z)
        top = b["pane_y"] if b else 0
        z.wait(lambda: any("line 30" in r for r in z.screen()), 15)   # it scrolls by now
        seen = []
        for _ in range(6):
            z.pump(0.5)
            s = vt.Screen(80, 20); s.feed(z.out)
            rows = [plain(r) for r in s.lines()]
            last = max((int(m) for r in rows for m in re.findall(r"line (\d+)", r)), default=0)
            seen.append((rows[top - 1].strip(), last))
        need("lines: the row over the bar is the line, every time (%r)" % [a for a, _ in seen],
             all(a and set(a) <= set("─┴┼") for a, _ in seen))
        need("lines: the pane's newest line shows on the screen (%r)" % [n for _, n in seen],
             all(n > 30 for _, n in seen) and seen[-1][1] > seen[0][1])

if fails:
    print("bar-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("bar-check ok")
