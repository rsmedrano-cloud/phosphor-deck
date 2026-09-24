#!/usr/bin/env python3
"""phosphor notify marks the tab it came from (or SYS with none) with
"<TAB> ●N", the same mechanism mentions.py already uses for COMMS -- but
with notifier=false (the default, no floating panes), so a notification
otherwise leaves no trace on screen (see #26). tabmark.tick() clears the
mark once someone's actually on that tab; COMMS is skipped, mentions.py
already owns that one.

    python3 tests/tabmark-check.py

Needs zellij; without it, it says so and passes (same as edit-check.py).
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zjprobe

PROFILE = '''
[deck]
session = "tabmark"

[[hosts]]
name = "box"
role = "brain"
local = true
''' + "\n".join('[[tabs]]\nname = "%s"\npanes = [ { cmd = "" } ]\n' % n
                for n in ("SYS", "COMMS", "T1", "T2"))

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

def names(z):
    """{tab_id: name}, straight from zellij's own state."""
    out = subprocess.run([z.zj, "-s", z.session, "action", "list-tabs", "--state", "--json"],
                         env=z.env, capture_output=True, text=True, timeout=10).stdout
    return {str(t["tab_id"]): t["name"] for t in json.loads(out)}

def by_name(z, base):
    """The one open tab whose name, mark stripped, is `base`."""
    for n in names(z).values():
        if n.split(" ●")[0].strip() == base:
            return n
    return None

def notify(z, *args):
    p = subprocess.run([os.path.join(z.env["HOME"], ".local/bin/phosphor"), "notify",
                        "--no-tts", "--no-push"] + list(args),
                       env=z.env, capture_output=True, timeout=10)
    assert p.returncode == 0, p.stderr

def tick(z):
    z.py("import tabmark; tabmark.tick(%r)" % z.session)

if not zjprobe.zellij():
    print("ok — zellij isn't installed, skipping"); sys.exit(0)

with zjprobe.Probe(PROFILE, session="tabmark") as z:
    # A notify naming a tab marks it, with no floating panes involved
    # (notifier isn't even set -- defaults false).
    notify(z, "--tab", "T1", "one thing happened")
    need("T1 got marked", by_name(z, "T1") == "T1 ●1")
    need("T2 untouched", by_name(z, "T2") == "T2")

    # A second notify to the same tab bumps the count.
    notify(z, "--tab", "T1", "another thing")
    need("T1's count went up", by_name(z, "T1") == "T1 ●2")

    # No --tab at all: SYS.
    notify(z, "unaddressed")
    need("SYS got marked", by_name(z, "SYS") == "SYS ●1")

    # COMMS is mentions.py's own tab -- tabmark leaves it alone even if
    # something calls notify --tab COMMS directly.
    notify(z, "--tab", "COMMS", "a chat message, sort of")
    need("COMMS was left for mentions.py to mark, not touched here", by_name(z, "COMMS") == "COMMS")

    # Arriving at T1 and ticking clears its mark; T2 (never marked) and the
    # still-unread SYS mark are untouched. A real keystroke, not `action
    # go-to-tab-name`: that CLI action doesn't move the client already
    # attached in the pty, only its own ephemeral one.
    z.keys(b"\x1b3", 0.5)   # Alt-3: the deck's default tab-switch key, tab 3 = T1
    tick(z)
    need("visiting T1 cleared its mark", by_name(z, "T1") == "T1")
    need("SYS is still marked -- nobody looked at it", by_name(z, "SYS") == "SYS ●1")

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok — phosphor notify marks the tab it came from, cleared on arrival")
