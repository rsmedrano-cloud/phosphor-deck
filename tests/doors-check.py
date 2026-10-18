#!/usr/bin/env python3
"""Every public command has a door in the deck, not only a typed one.

    python3 tests/doors-check.py

A command reachable only by searching (e in DECK, / in +) is one nobody
finds. So every public entry of share/commands.json declares its `card`
(_schema says what each field means), and this checks:

- the card is well formed for its kind: a sensor or toggle names its state,
  a toggle its on and off arguments, plumbing says why it has no card;
- every argument a card passes (from, on, off, args) is one the command
  takes (lib/cli.py's check, and its fixed words);
- a card whose command changes things on a bare run asks first (confirm);
- a sensor's or toggle's state comes from the command's own --json;
- `tui`, when there, is true: a screen of its own, no wait after it;
- the DECK tab's keys (lib/panel.py's OPENS) name real commands, one entry
  per key.

- the gallery (lib/dash.py, + on any dashboard and `cards` in the +
  menu) holds every card that isn't plumbing, so no card is left without
  a door.

- every command with a card has a door in the deck besides typing it and
  the gallery: a DECK key, a + menu or fleet entry, a pane in a shipped
  shape or the layout, a card of SYS's row, a key of the deck (Alt-j...);
  or its `no_door` says why it needs none. A `no_door` on a command that
  has a door is stale, and fails too. Three ways to every function: the
  command, the card, the deck.
"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli
bad = []

KINDS = {"sensor":   ({"state"}, {"from", "tui"}),
         "toggle":   ({"state", "on", "off"}, {"from", "ask", "confirm"}),
         "button":   (set(), {"args", "ask", "confirm", "tui"}),
         "shortcut": (set(), {"args", "ask", "confirm", "tui"}),
         "plumbing": ({"why"}, set())}
LISTS = ("from", "on", "off", "args", "ask")

def strs(v):
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v)

entries = cli.entries(hidden=True)
cards = {}
for name, e in entries.items():
    where = "share/commands.json: `%s`" % name
    c = e.get("card")
    if e.get("hidden"):
        if c is not None:
            bad.append("%s is hidden: it has no card" % where)
        continue
    if not isinstance(c, dict):
        bad.append("%s has no card: give it one (sensor, toggle, button, shortcut, or plumbing with why)" % where)
        continue
    kind = c.get("kind")
    if kind not in KINDS:
        bad.append("%s: card kind %r isn't one of %s" % (where, kind, ", ".join(KINDS)))
        continue
    need, may = KINDS[kind]
    for f in sorted(need - set(c)):
        bad.append("%s: a %s card needs `%s`" % (where, kind, f))
    for f in sorted(set(c) - need - may - {"kind"}):
        bad.append("%s: a %s card has no `%s`" % (where, kind, f))
    for f in LISTS:
        if f in c and not strs(c[f]) and not (f in ("on", "args") and c[f] == []):
            bad.append("%s: card `%s` should be a list of words" % (where, f))
    for f in ("state", "why"):
        if f in c and not (isinstance(c[f], str) and c[f].strip()):
            bad.append("%s: card `%s` should be a non-empty string" % (where, f))
    if "confirm" in c and c["confirm"] is not True:
        bad.append("%s: card `confirm` is true or left out" % where)
    if "tui" in c and c["tui"] is not True:
        bad.append("%s: card `tui` is true or left out" % where)
    if kind == "shortcut" and not (c.get("args") or c.get("ask")):
        bad.append("%s: a shortcut goes somewhere: give it args or ask (else it's a button)" % where)
    # a tap that changes things asks first; typing what it asks for is asking.
    # A sensor's tap opens the panel it summarizes (fleet's watchdog is the panel's)
    if kind not in ("plumbing", "sensor") and e.get("mutates") and not (c.get("confirm") or c.get("ask")):
        bad.append("%s changes things on a bare run: its card needs confirm" % where)
    # what the card passes has to be something the command takes
    words = set(cli.words(e))
    for f in ("from", "on", "off", "args"):
        argv = c.get(f)
        if not strs(argv):
            continue
        flag = cli.check(name, argv)
        if flag:
            bad.append("%s: card `%s` passes %s, which it doesn't take" % (where, f, flag))
        for w in argv:
            if not w.startswith("-") and e.get("words") and w not in words:
                bad.append("%s: card `%s` passes `%s`, not one of its words" % (where, f, w))
    if "state" in c and ("--json" not in c.get("from", ["--json"]) or "--json" not in e.get("options", [])):
        bad.append("%s: a %s card's state comes from the command's --json: give it one, and say so in from"
                   % (where, kind))
    cards[name] = c

# the DECK tab's keys, as data
import panel
keys = {a[0] for a in panel.ACTIONS} | {"f", "P"}
if set(panel.OPENS) != keys:
    bad.append("lib/panel.py: OPENS should name every key's commands, no more: %s"
               % " ".join(sorted(set(panel.OPENS) ^ keys)))
for k, cmds in panel.OPENS.items():
    for c in cmds:
        if c not in entries:
            bad.append("lib/panel.py: OPENS[%r] names `%s`, which isn't a command" % (k, c))

# today's other doors: + menu and fleet entries, panes in the shipped shapes
doors = {c for cmds in panel.OPENS.values() for c in cmds}
PANE = re.compile(r'"?cmd"?\s*[=:]\s*\\?"phosphor ([a-z-]+)')
ARGV = re.compile(r'PHOSPHOR, "([a-z-]+)"')        # the + menu's entries run it directly
KDL = re.compile(r"args \\?\"([a-z-]+)\\?\"")      # the layout's own panes: + is phosphor new
for rel, pats in (("lib/newtab.py", (PANE, ARGV)), ("lib/fleet.py", (PANE,)), ("lib/init.py", (PANE,)),
                  ("lib/recipe.py", (PANE,)), ("profiles/example.toml", (PANE,)), ("lib/gen.py", (KDL,))):
    text = open(os.path.join(ROOT, rel)).read()
    for pat in pats:
        doors |= set(pat.findall(text))
import init, shortcuts   # SYS's row and the deck's keys
doors |= set(init.sys_cards(web=True, tun=("t",), ci=True)) | {"usage"}   # SYS's row, all it may hold
doors |= set(re.findall(r'RUN % \("([a-z-]+)', open(shortcuts.__file__).read()))   # Alt-j's note...
import dash
gallery = set(dash.gallery_names())
gone = {d["name"] for d in cli.deprecations("command")}
for n, c in cards.items():
    if c["kind"] != "plumbing" and n not in gallery and n not in gone and not entries[n].get("hidden"):
        bad.append("%s has a %s card the gallery (lib/dash.py) doesn't offer" % (n, c["kind"]))
for c in doors:
    if c not in entries and c != "panel":
        bad.append("a deck door opens `phosphor %s`, which isn't a command" % c)

for n, c in cards.items():
    why = entries[n].get("no_door")
    if why is not None and not (isinstance(why, str) and why.strip()):
        bad.append("share/commands.json: `%s`'s no_door should say why, in words" % n)
    elif c["kind"] == "plumbing":
        if why is not None:
            bad.append("share/commands.json: `%s` is plumbing: its card's why says it, not no_door" % n)
    elif n in doors and why:
        bad.append("share/commands.json: `%s` has a door in the deck now: drop its no_door" % n)
    elif n not in doors and not why and n not in gone:
        bad.append("`%s` is only typed or in the gallery: give it a door in the deck (a DECK key, "
                   "the + menu, a pane...) or say why not in its no_door" % n)

if bad:
    print("doors-check FAILED:")
    for b in bad:
        print("  - " + b)
    sys.exit(1)
only_card = sorted(n for n, c in cards.items() if c["kind"] != "plumbing" and n not in doors)   # each says why
by_kind = {}
for c in cards.values():
    by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
print("doors-check ok (%d cards: %s)" % (len(cards), ", ".join("%d %s" % (v, k) for k, v in sorted(by_kind.items()))))
print("  no door in the deck, on purpose (no_door): " + (" ".join(only_card) or "none"))
