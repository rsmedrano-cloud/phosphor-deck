#!/usr/bin/env python3
"""FLEET's keys: pick a card (arrows, Tab, a tap), then s opens a shell on
that machine, l its logs, t a triage, a its actions -- each in a tab of its own.

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
need("u: phosphor upkeep upgrade, in a tab", fleet.action_tab("u", "db-box", "deploy@db-box-alias")
     == ("UPGRADE-DB-BOX", {"cmd": "phosphor upkeep", "args": ["upgrade", "db-box"]}))
need("b: phosphor upkeep reboot, in a tab", fleet.action_tab("b", "db-box", None)
     == ("REBOOT-DB-BOX", {"cmd": "phosphor upkeep", "args": ["reboot", "db-box"]}))
need("f: phosphor upkeep units, in a tab", fleet.action_tab("f", "db-box", "deploy@db-box-alias")
     == ("UNITS-DB-BOX", {"cmd": "phosphor upkeep", "args": ["units", "db-box"]}))
need("a: phosphor upkeep run, its list, in a tab", fleet.action_tab("a", "db-box", "deploy@db-box-alias")
     == ("RUN-DB-BOX", {"cmd": "phosphor upkeep", "args": ["run", "db-box"]}))
need("any other key opens nothing", fleet.action_tab("x", "db-box", None) is None)

# upkeep: over ssh -t for a remote host, here for the brain; a name the
# fleet doesn't watch and a run without a terminal never get that far
import upkeep
prof = {"hosts": [{"name": "box", "role": "brain", "local": True},
                  {"name": "db-box", "role": "node", "ssh": "db-box-alias", "user": "deploy"}]}
need("upkeep: a remote host's target", upkeep.where("db-box", prof) == ("db-box", "deploy@db-box-alias"))
need("upkeep: the brain runs here", upkeep.where("box", prof) == ("box", None))
need("upkeep: an unknown name", upkeep.where("nimbus", prof) is None)
a = upkeep.argv("upgrade", "deploy@db-box-alias")
need("upkeep upgrade: ssh -t, one sh -c, every manager it knows",
     a[:3] == ["ssh", "-t", "deploy@db-box-alias"] and len(a) == 4 and a[3].startswith("sh -c ")
     and all(m in a[3] for m in ("apt-get", "dnf", "pacman", "zypper", "apk")))
need("upkeep reboot on the brain: right here", upkeep.argv("reboot", None) == ["sh", "-c", "sudo systemctl reboot"])
ran = []
upkeep.subprocess = type("never", (), {"call": staticmethod(lambda c: ran.append(c) or 0)})
_stdin, sys.stdin = sys.stdin, open(os.devnull)
need("upkeep: an unknown name runs nothing", upkeep.run("reboot", "nimbus", prof) == 2)
need("upkeep: no terminal, nothing runs", upkeep.run("upgrade", "db-box", prof) == 2 and not ran)
sys.stdin = _stdin

# runbooks: [[hosts.actions]], a name and a run; only y runs one, and a
# host without them (or a name it doesn't have) runs nothing
prof["hosts"][1]["actions"] = [{"name": "restart jellyfin", "run": "docker restart jellyfin"},
                               {"name": "no run"}, {"run": "no name"},
                               {"name": "clear tmp", "run": "sudo rm -rf /tmp/x"}]
need("upkeep: a host's actions, the broken ones left out",
     upkeep.actions("db-box", prof) == [("restart jellyfin", "docker restart jellyfin"),
                                        ("clear tmp", "sudo rm -rf /tmp/x")])
need("upkeep: no actions on the brain", upkeep.actions("box", prof) == [])
need("upkeep run: the action's own line over ssh -t",
     upkeep.argv("run", "deploy@db-box-alias", "docker restart jellyfin")
     == ["ssh", "-t", "deploy@db-box-alias", "sh -c 'docker restart jellyfin'"])
_stdin, sys.stdin = sys.stdin, open(os.devnull)
need("upkeep run: no terminal, nothing runs", upkeep.run("run", "db-box", prof, "clear tmp") == 2 and not ran)
sys.stdin = _stdin
class _Tty:
    def isatty(self): return True
answers = []
upkeep.ask = lambda p: answers.pop(0) if answers else None
_stdin, sys.stdin = sys.stdin, _Tty()
answers[:] = ["n"]
need("upkeep run: anything but y leaves it alone", upkeep.run("run", "db-box", prof, "clear tmp") == 1 and not ran)
answers[:] = ["y"]
need("upkeep run: y runs the one named",
     upkeep.run("run", "db-box", prof, "clear tmp") == 0 and ran.pop() == upkeep.argv("run", "deploy@db-box-alias", "sudo rm -rf /tmp/x"))
answers[:] = ["1", "y"]
need("upkeep run: no ACTION, picked from the list by number",
     upkeep.run("run", "db-box", prof) == 0 and ran.pop()[-1] == "sh -c 'docker restart jellyfin'")
answers[:] = [""]
need("upkeep run: Enter at the list leaves", upkeep.run("run", "db-box", prof) == 1 and not ran)
answers[:] = ["y"]
need("upkeep run: a name it doesn't have runs nothing", upkeep.run("run", "db-box", prof, "nope") == 1 and not ran)
need("upkeep run: a host without actions runs nothing", upkeep.run("run", "box", prof) == 2 and not ran)

# upkeep units (#81): every failed unit's status and journal, then one fixed
# on a y, then the list again from the host, until none is left
show = lambda units: upkeep.argv("run", "deploy@db-box-alias", upkeep.SHOW, units)
need("upkeep units: the units go to the status script as its \"$@\"",
     show(["getty@tty1.service"])[-1].endswith("' sh getty@tty1.service") and show(["a"])[:3] == ["ssh", "-t", "deploy@db-box-alias"])
left = [["getty@tty1.service", "media-remount.service"], ["media-remount.service"], []]
upkeep.failed_now = lambda t: left.pop(0) if left else []
answers[:] = ["x 1", "y", "r", "y"]
need("upkeep units: x N resets one, r the only one restarts it, then none is left",
     upkeep.run("units", "db-box", prof) == 0
     and ran == [show(["getty@tty1.service", "media-remount.service"]),
                 upkeep.argv("run", "deploy@db-box-alias", "sudo systemctl reset-failed getty@tty1.service"),
                 show(["media-remount.service"]),
                 upkeep.argv("run", "deploy@db-box-alias", "sudo systemctl restart media-remount.service")])
for said, why in ((["r 1", "n"], "anything but y"), ([""], "Enter"), (["r 5"], "a number it doesn't list"),
                  (["restart"], "a word it doesn't know")):
    ran.clear(); left[:] = [["a.service", "b.service"]]; answers[:] = said
    need("upkeep units: %s fixes nothing" % why, upkeep.run("units", "db-box", prof) == 1 and ran == [show(["a.service", "b.service"])])
ran.clear()
upkeep.failed_now = lambda t: None
need("upkeep units: a host that doesn't answer runs nothing", upkeep.run("units", "db-box", prof) == 2 and not ran)
sys.stdin = _stdin

# FLEET's footer: a only on a card that has actions
fleet.HOSTS = [("box", None), ("db-box", "deploy@db-box-alias")]
fleet._acts.update(mtime=0, names={"db-box"})
_gm, fleet.os.path.getmtime = fleet.os.path.getmtime, lambda p: 0
def bare(t): return re.sub(r"\x1b\[[0-9;]*m", "", t)
need("footer: a actions on a card that has some", "a actions" in bare(fleet.footer(2, 1, "")[0]))
need("footer: no a on one without", "a actions" not in bare(fleet.footer(2, 0, "")[0]))
_rs, fleet.read_state = fleet.read_state, lambda: {"db-box": {"ok": True, "SVCFAIL": 1}, "box": {"ok": True, "SVCFAIL": 0}}
need("footer: f failed on a card whose units failed", "f failed" in bare(fleet.footer(2, 1, "")[0]))
need("footer: no f on one without", "f failed" not in bare(fleet.footer(2, 0, "")[0]))
fleet.read_state = _rs
fleet.os.path.getmtime = _gm

# profcheck: what doctor says about a broken action
import profcheck
got = []
profcheck._actions("[[hosts]] db-box", [{"name": "x", "run": "true"}, {"name": "x", "run": "true"},
                                         {"name": "y"}, {"run": "z"}, {"name": "w", "run": "t", "sudo": True}], got)
said = " | ".join(m for _, m in got)
need("profcheck: a repeated name, a missing run or name, an unknown key",
     "two actions with that name" in said and "run is the command line" in said
     and "a name, to pick it by" in said and "sudo" in said)

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

# grid(): no line wider than the pane, however narrow (a phone's SYS, with
# the adjutant beside fleet, leaves it ~17 columns); zellij wraps a longer one
import ui
d = {"ok": True, "CPU": 37, "MEMU": 40300, "MEMT": 65536, "LOAD": "1.56 1.40 1.25",
     "mnt": [["/mnt/backup", 95, "8T"]], "UP": "12d"}
fleet.HOSTS = [("box", None), ("db-box", "db-box-alias"), ("nimbus", None)]
for cols in (17, 30, 120):
    lines, cw, per_row, h = fleet.grid(cols, 40, {"box": d, "db-box": d})
    worst = max(ui.vlen(l) for l in lines)
    need("grid at %d columns: lines fit (widest %d)" % (cols, worst), worst <= cols)
    need("grid at %d columns: a card fits the pane" % cols, cw <= cols)
need("a wide pane still puts the cards side by side", fleet.grid(120, 40, {})[2] == 3)
need("vcut keeps the colors and cuts by what shows",
     ui.vlen(ui.vcut(ui.RED + "abcdef" + ui.RST + "gh", 4)) == 4
     and ui.vcut(ui.RED + "abcdef", 4).startswith(ui.RED + "abcd"))
need("vcut leaves a short line alone", ui.vcut("abc", 9) == "abc")

# Esc: drops the pick; with none, FLEET ends when opened over something, never as SYS's pane
import zoom
_back, _tapped, _own = zoom.back, zoom.tapped, zoom.own_pane
zoom.back = lambda: False
zoom.tapped = lambda: False
zoom.own_pane = lambda: True
need("Esc with a pick drops it", fleet.on_esc(2) == (None, False))
need("Esc with none: the SYS panel stays", fleet.on_esc(None) == (None, False))
zoom.own_pane = lambda: False
need("Esc with none, typed in a shell: back to it", fleet.on_esc(None) == (None, True))
zoom.own_pane = lambda: True
zoom.tapped = lambda: True
need("Esc with none, opened from a card: back to the cards", fleet.on_esc(None) == (None, True))
need("Esc with a pick, opened from a card: only drops it", fleet.on_esc(0) == (None, False))
zoom.back, zoom.tapped, zoom.own_pane = _back, _tapped, _own

# the demo's machines aren't real: no tab, no ssh
fleet.DEMO = True
need("demo: refuses", "demo" in fleet.open_action("s", "box", None))
# ...unless a recording gave that name a Host alias of its own: s and l open
import init, tempfile
_home = init.HOME
init.HOME = tempfile.mkdtemp()
os.makedirs(os.path.join(init.HOME, ".ssh"))
with open(os.path.join(init.HOME, ".ssh/config"), "w") as f:
    f.write("Host forge\n    HostName localhost\n")
need("demo: an ssh alias opens s", fleet.demo_alias("forge"))
need("demo: a made-up name still doesn't", not fleet.demo_alias("vault"))
need("demo: t still refuses with an alias", "demo" in fleet.open_action("t", "forge", "forge"))
_zj = os.environ.pop("ZELLIJ", None)     # never a real tab from here
need("demo: s with an alias gets past the demo check",
     "inside the deck" in fleet.open_action("s", "forge", "forge"))
if _zj is not None:
    os.environ["ZELLIJ"] = _zj
init.HOME = _home
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

[[hosts.actions]]
name = "restart jellyfin"
run = "docker restart jellyfin"

[[tabs]]
name = "SYS"
panes = [ { cmd = "phosphor fleet" } ]
'''
    with zjprobe.Probe(PROFILE, session="fleetkeys") as z:
        need("fleet came up with its hint", z.wait(lambda: "tap a machine" in z.text(), 20))
        def opened(tab):
            return z.wait(lambda: tab in z.tabs(), 10)
        def back():
            # wait until fleet itself is on screen again: on a slow runner a
            # key sent right after the switch can land before SYS has focus
            z.action("go-to-tab-name", "SYS"); z.pump(1)
            z.wait(lambda: "h history" in z.text(), 10)
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
        need("db-box has actions: a shows on its bottom line", any("a actions" in r for r in z.screen()))
        z.keys("a", 1)
        need("a: a RUN-DB-BOX tab, its list, waiting", opened("RUN-DB-BOX")
             and z.wait(lambda: "restart jellyfin" in z.text() and "which one" in z.text(), 10))
        back()
        z.keys("\x1b", 1.5)
        z.keys("s", 0)
        need("Esc drops the pick, and s then only asks for one",
             z.wait(lambda: "pick a machine first" in z.text()) and z.tabs().count("DB-BOX") == 0)

if fails:
    print("FAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok")
