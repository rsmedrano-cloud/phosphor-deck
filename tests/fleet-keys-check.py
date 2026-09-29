#!/usr/bin/env python3
"""FLEET's keys: pick a card (arrows, Tab, a tap), then s opens a shell on
that machine, l its logs, t a triage -- each in a tab of its own.

    python3 tests/fleet-keys-check.py           # the pieces, no zellij
    python3 tests/fleet-keys-check.py --live    # also in a throwaway zellij

--live needs zellij; without it, it says so and passes (same as edit-check.py).
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import fleet, gen

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

# action_tab(): what each key opens, for a remote host and for the brain
name, spec = fleet.action_tab("s", "db-box", "deploy@db-box-alias")
need("s on a remote host: an ssh pane to its target", (name, spec) == ("DB-BOX", {"ssh": "deploy@db-box-alias"}))
name, spec = fleet.action_tab("s", "box", None)
need("s on the brain: a plain shell", name == "BOX" and "ssh" not in spec and "cmd" not in spec)
name, spec = fleet.action_tab("l", "db-box", "deploy@db-box-alias")
need("l on a remote host: journalctl over ssh, reconnecting",
     name == "TAIL-DB-BOX" and spec["_run"][:3] == ["ssh", "-t", "deploy@db-box-alias"]
     and "journalctl" in spec["_run"] and spec["reconnect"])
name, spec = fleet.action_tab("l", "box", None)
need("l on the brain: journalctl right here", spec["_run"][0] == "journalctl" and not spec["reconnect"])
name, spec = fleet.action_tab("t", "db-box", "deploy@db-box-alias")
need("t: phosphor triage on that host", (name, spec) == ("TRIAGE-DB-BOX", {"cmd": "phosphor triage", "args": ["db-box"]}))
need("any other key opens nothing", fleet.action_tab("x", "db-box", None) is None)

# the l spec becomes a pane that runs that argv through phosphor run
kdl = gen.pane_kdl(fleet.action_tab("l", "db-box", "db-box-alias")[1], gen.Ctx({}), 0)
need("l's pane: phosphor run --reconnect around the ssh",
     '"--reconnect"' in kdl and '"ssh" "-t" "db-box-alias" "journalctl"' in kdl and 'name="TAIL-DB-BOX"' in kdl)

# card_at(): cards 30 wide, a 1-column gap, 3 per row, 12 lines tall, 5 hosts
need("a tap on the first card", fleet.card_at(1, 1, 30, 1, 3, 12, 5) == 0)
need("a tap on the second card's last column", fleet.card_at(61, 5, 30, 1, 3, 12, 5) == 1)
need("a tap in the gap: nothing", fleet.card_at(31, 5, 30, 1, 3, 12, 5) is None)
need("a tap on the second row", fleet.card_at(35, 13, 30, 1, 3, 12, 5) == 4)
need("a tap past the last card: nothing", fleet.card_at(70, 13, 30, 1, 3, 12, 5) is None)

# move(): arrows and Tab, never off the ends
need("the first arrow picks the first card", fleet.move(None, "\x1b[C", 3, 5) == 0)
need("right", fleet.move(0, "\x1b[C", 3, 5) == 1)
need("Tab", fleet.move(1, "\t", 3, 5) == 2)
need("down a row", fleet.move(1, "\x1b[B", 3, 5) == 4)
need("down past the end stays", fleet.move(2, "\x1b[B", 3, 5) == 2)
need("left past the start stays", fleet.move(0, "\x1b[D", 3, 5) == 0)

# footer(): with a card picked, every hint can be tapped where it's drawn
fleet.HOSTS = [("box", None), ("db-box", "db-box-alias")]
line, taps = fleet.footer(2, 1, "")
plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
for (a, b), k in taps.items():
    shown = plain[a - 1:b]
    need("the tap range for %r covers its hint (got %r)" % (k, shown),
         shown.startswith("Esc" if k == "\x1b" else k))
need("nothing picked: no hints to tap", fleet.footer(2, None, "")[1] == {})

# the demo's machines aren't real: no tab, no ssh
fleet.DEMO = True
need("demo: refuses", "demo" in fleet.open_action("s", "box", None))
fleet.DEMO = False

if "--live" in sys.argv:
    import zjprobe
    if not zjprobe.zellij():
        print("ok — zellij isn't installed, skipping the live part"); sys.exit(1 if fails else 0)
    PROFILE = '''
[deck]
session = "fleetkeys"

[[hosts]]
name = "box"
role = "brain"
local = true

[[hosts]]
name = "db-box"
role = "storage"
ssh = "db-box.invalid"

[[tabs]]
name = "SYS"
panes = [ { cmd = "phosphor fleet" } ]
'''
    with zjprobe.Probe(PROFILE, session="fleetkeys") as z:
        need("fleet came up with its hint", z.wait(lambda: "tap a machine" in z.text(), 20))
        def opened(tab):
            return z.wait(lambda: tab in z.tabs(), 10)
        def back():
            z.action("go-to-tab-name", "SYS"); z.pump(1)
        z.keys("\x1b[C", 1.5)                        # picks box
        z.keys("s", 1)
        need("s: a BOX tab (a shell on the brain)", opened("BOX"))
        back()
        z.keys("\x1b[C", 1.5)                        # db-box
        z.keys("l", 1)
        need("l: a TAIL-DB-BOX tab", opened("TAIL-DB-BOX"))
        back()
        z.keys("t", 1)
        need("t: a TRIAGE-DB-BOX tab", opened("TRIAGE-DB-BOX"))
        back()
        z.keys("\x1b", 1.5)
        z.keys("s", 1.5)
        need("Esc drops the pick, and s then only asks for one",
             "pick a machine first" in z.text() and z.tabs().count("DB-BOX") == 0)

if fails:
    print("FAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok")
