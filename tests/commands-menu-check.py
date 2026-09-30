#!/usr/bin/env python3
"""phosphor commands: category/command lists cover every real subcommand,
and its detail screen only auto-runs what share/commands.json calls safe.

    python3 tests/commands-menu-check.py
"""
import builtins, io, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import commands

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# CATEGORIES covers exactly the USAGE-derived command set, plus "help"
# (which -- like "run" and "mention-hook" -- isn't a `phosphor X` line in
# USAGE itself, but belongs in a browsable index).
usage = open(os.path.join(ROOT, "phosphor")).read().split('USAGE = """', 1)[1].split('"""', 1)[0]
from_usage = set(re.findall(r"^\s*phosphor ([a-z][a-z-]*)", usage, re.M))
in_menu = {cmd for _, cmds in commands.CATEGORIES for cmd, _, _ in cmds}
check("every USAGE command is in the menu", from_usage <= in_menu)
check("the menu has no command USAGE doesn't (beyond 'help')", in_menu - from_usage == {"help"})

# category_items(): one row per category, "Before you push a fork" shortened
cats = commands.category_items()
check("one row per category", len(cats) == len(commands.CATEGORIES))
short = next(c for c in cats if c[2] == "Before you push a fork")
check("long category name shortened for the 16-char label column", short[0] == "Before you push")
check("shortened name still fits pick()'s label column", len(short[0]) <= 16)
for label, note, name, cmds in cats:
    check("label %r fits the picker's column" % label, len(label) <= 16)

# command_items(): (cmd, note, usage) tuples, note is what pick() shows
first_cat_cmds = commands.CATEGORIES[0][1]
items = commands.command_items(first_cat_cmds)
check("command_items shape", items[0] == (first_cat_cmds[0][0], first_cat_cmds[0][2], first_cat_cmds[0][1]))

# detail(): only runs on Enter when the manifest says mutates: false; 'c'
# always copies, regardless of safety; never touches a real terminal or
# a real assistant/clipboard here.
import contextlib
real_screen, real_getkey, real_run, real_input = commands.screen, commands.getkey, commands.subprocess.run, builtins.input
commands.screen = lambda lines: None
# detail() waits on back() (q, Esc or Enter) after running a safe command --
# on a real tty (a developer running sh tests/check.sh by hand, not CI's
# non-interactive stdin) that would block this test waiting for a real key.
builtins.input = lambda *a, **kw: ""
commands.back = lambda *a, **kw: None
ran = []
commands.subprocess.run = lambda cmd, **kw: ran.append(cmd)
copied = []
class FakeClip:
    @staticmethod
    def send(data):
        copied.append(data)
sys.modules["clip"] = FakeClip

def press(keys):
    it = iter(keys)
    commands.getkey = lambda timeout=None, text=False: next(it, "q")

try:
    with contextlib.redirect_stdout(io.StringIO()):
        # safe command: Enter runs it
        ran.clear()
        press(["\r"])
        commands.detail("doctor", "phosphor doctor", "note", {"doctor": {"mutates": False}})
        check("safe command runs on Enter", ran and ran[-1][:2] == [sys.executable, commands.PHOSPHOR]
              and ran[-1][2] == "doctor")

        # mutating command: Enter does nothing (falls through, stays on screen,
        # 'q' right after actually exits the loop)
        ran.clear()
        press(["\r", "q"])
        commands.detail("restart", "phosphor restart", "note", {"restart": {"mutates": True}})
        check("mutating command: Enter never runs it", not ran)

        # a command that asks for what it needs (lib/form.py): Enter runs it
        # bare, even though it can mutate -- its own screens ask the rest
        ran.clear()
        press(["\r"])
        commands.detail("send", "phosphor send FILE", "note", {"send": {"mutates": True}})
        check("a command that asks: Enter runs it with no arguments", ran and ran[-1][2:] == ["send"])
        check("every command that asks is a real one", commands.ASKS <= in_menu)

        # unknown command (not in the manifest at all): treated as unsafe, never auto-run
        ran.clear()
        press(["\r", "q"])
        commands.detail("mystery", "phosphor mystery", "note", {})
        check("no manifest entry: never auto-run either", not ran)

        # 'c' copies the usage line, for both safe and unsafe commands
        copied.clear()
        press(["c", "q"])
        commands.detail("send", "phosphor send FILE", "note", {"send": {"mutates": True}})
        check("'c' copies the usage line", copied == [b"phosphor send FILE"])

        # q/Esc/b all just leave, no side effects
        for key in ("q", "\x1b", "b"):
            ran.clear(); copied.clear()
            press([key])
            commands.detail("doctor", "phosphor doctor", "note", {"doctor": {"mutates": False}})
            check("%r leaves with no side effects" % key, not ran and not copied)

        # find(): name, usage, note and category, case-insensitive, menu order
        check("find by name", [c for c, _, _ in commands.find("broadcast")] == ["broadcast"])
        check("find: the name matching comes first", commands.find("tail")[0][0] == "tail")
        check("find by a word in the note", "tunnel" in [c for c, _, _ in commands.find("LocalForward")])
        check("find by category", {c for c, _, _ in commands.find("session")} >= {"restart", "down"})
        check("find: blank query finds nothing", commands.find("  ") == [])
        check("find: no match is empty", commands.find("zzqx") == [])

        # ask_query(): typing, Backspace, Enter returns it; Esc cancels
        press(list("logx") + ["\x7f", "s", "\r"])
        check("ask_query returns what was typed", commands.ask_query() == "logs")
        press(["journal", "\r"])                         # pasted: one read, many chars
        check("ask_query takes a paste whole", commands.ask_query() == "journal")
        press(["a", "\x1b"])
        check("ask_query: Esc cancels", commands.ask_query() is None)

        # main(): '/' on the categories, a query, pick a match, its detail
        picks = iter(["/", ("logs", "note", "phosphor logs"), None, None])
        titles = []
        real_pick = commands.edit.pick
        def fake_pick(title, items, extra=()):
            titles.append((title, items, extra))
            return next(picks)
        commands.edit.pick = fake_pick
        shown = []
        real_detail = commands.detail
        commands.detail = lambda cmd, usage, note, man: shown.append(cmd)
        press(list("logs") + ["\r"])
        try:
            commands.main()
        finally:
            commands.edit.pick, commands.detail = real_pick, real_detail
        check("categories offer '/'", ("/", "search every command") in titles[0][2])
        check("search results titled with the query", titles[1][0].endswith("for 'logs'"))
        check("search results are find()'s", titles[1][1] == commands.find("logs"))
        check("a picked match opens its detail", shown == ["logs"])
finally:
    commands.screen, commands.getkey, commands.subprocess.run = real_screen, real_getkey, real_run
    builtins.input = real_input
    del sys.modules["clip"]

if fails:
    print("commands-menu-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("commands-menu-check ok")
