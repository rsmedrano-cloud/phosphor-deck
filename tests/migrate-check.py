#!/usr/bin/env python3
"""phosphor migrate: an older profile gets each pending step (the DECK tab
in one pane, [deck] tts into [tts] enabled, [deck] notifier and
notify_seconds dropped) and version = CURRENT, through
write_profile with a .bak; an up-to-date or newer profile is left alone; a
profile init writes is already current; doctor, gen, update and the DECK
tab only speak up when there's something to change. An offer (a new
default, sys-cards first) is asked on its own: taken it lands, declined it
goes into [deck] declined and is never offered again, "later" leaves it;
each shape without it gets it back exactly as init writes it.

    python3 tests/migrate-check.py
"""
import contextlib, io, os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import deckconf, migrate

fails = []
def check(what, ok):
    if not ok: fails.append(what)

OLD = ('[deck]\nsession = "deck"\ntts = true\n\n'
       '[[tabs]]\nname  = "SYS"\npanes = [ { cmd = "phosphor fleet" } ]\n\n'
       '[[tabs]]\nname  = "DECK"\nsplit = "cols"\npanes = [\n  { cmd = "phosphor panel", size = "50%" },\n'
       '  { cmd = "phosphor keys" },\n]\n\n[[tabs]]\nname  = "NOTES"\npanes = [ { cmd = "phosphor notes" } ]\n')

steps, new, ver = migrate.plan(OLD)
after = deckconf.tomllib.loads(new)
check("no version is version 1", ver == 1)
check("both steps are pending", len(steps) == 2)
check("the DECK tab is one pane",
      [p.get("cmd") for t in after["tabs"] if t["name"] == "DECK" for p in t["panes"]] == ["phosphor panel"])
check("the other tabs stay, in order", [t["name"] for t in after["tabs"]] == ["SYS", "DECK", "NOTES"])
check("[deck] tts is gone", "tts" not in after["deck"])
check("[tts] enabled took its value", after.get("tts", {}).get("enabled") is True)
check("version = CURRENT", migrate.version(after) == migrate.CURRENT)
check("planning twice changes nothing more", migrate.plan(new)[1] == new and not migrate.plan(new)[0])

# a [tts] enabled already there wins over the old place
_, n2, _ = migrate.plan('[deck]\ntts = true\n\n[tts]\nenabled = false\n')
p2 = deckconf.tomllib.loads(n2)
check("an existing [tts] enabled is kept", p2["tts"]["enabled"] is False and "tts" not in p2["deck"])

# 3: the floating notice's keys go, whatever they said; a version 2
# profile gets only this step
N = '[deck]\nversion = 2\nnotifier = false   # flotantes apagados\nnotify_seconds = 5\nsplash = true\n\n[tts]\nenabled = true\n'
s4, n4, v4 = migrate.plan(N)
p4 = deckconf.tomllib.loads(n4)
check("version 2: only the notifier step", v4 == 2 and len(s4) == 1 and "notifier" in s4[0][0])
check("notifier and notify_seconds are gone", "notifier" not in p4["deck"] and "notify_seconds" not in p4["deck"])
check("the rest of [deck] stays", p4["deck"].get("splash") is True and p4["tts"]["enabled"] is True)
check("notifier = true goes too", "notifier" not in deckconf.tomllib.loads(migrate.plan('[deck]\nnotifier = true\n')[1])["deck"])

# headers written with spaces or a comment are still the same table:
# no second [deck] (which wouldn't parse), the DECK tab replaced, not added
COMMENTED = (OLD.replace("[deck]\n", "[deck]   # mine\n", 1)
                .replace('[[tabs]]\nname  = "DECK"', '[[tabs]]  # the panel\nname  = "DECK"', 1))
try:
    s3, n3, _ = migrate.plan(COMMENTED)
    p3 = deckconf.tomllib.loads(n3)
except Exception as e:
    s3, p3 = [], {"deck": {}, "tabs": []}; check("a commented header still parses: %s" % e, False)
check("commented headers: both steps", len(s3) == 2)
check("commented headers: one DECK tab, one pane",
      [[q.get("cmd") for q in t["panes"]] for t in p3["tabs"] if t["name"] == "DECK"] == [["phosphor panel"]])
check("commented headers: version in the one [deck]", migrate.version(p3) == migrate.CURRENT and "tts" not in p3["deck"])

# nothing to change: only the version, and nobody is nagged about it
steps, new, _ = migrate.plan('[deck]\nsession = "deck"\n')
check("a profile with nothing to change has no steps", steps == [])
check("...but migrate still stamps it", migrate.version(deckconf.tomllib.loads(new)) == migrate.CURRENT)
check("a profile with no [deck] gets one", migrate.version(deckconf.tomllib.loads(migrate.plan("")[1])) == migrate.CURRENT)

# a newer profile is never touched
newer = '[deck]\nversion = %d\ntts = true\n' % (migrate.CURRENT + 1)
check("a newer profile has nothing planned", migrate.plan(newer)[1] == newer)

# what init writes is already current
import init
txt = init.render([{"name": "db-box", "role": "brain", "local": True}], "p31", None)
check("init writes the current version", migrate.version(deckconf.tomllib.loads(txt)) == migrate.CURRENT
      and migrate.plan(txt)[1] == txt)
for name in ("example", "demo"):
    t = open(os.path.join(REPO, "profiles", name + ".toml")).read()
    check("profiles/%s.toml is current" % name, migrate.plan(t)[1] == t)

# main() on a real file: --dry-run writes nothing, yes writes it with a .bak,
# no writes nothing, and the result is what plan() said
d = tempfile.mkdtemp()
p = os.path.join(d, "deck.toml")
os.environ["PHOSPHOR_PROFILE"] = p
def run(*argv, answer=True, offer=2):
    real_yes, real_pick, real_argv = init.yes, init.pick, sys.argv
    init.yes = lambda *a, **kw: answer
    init.pick = lambda *a, **kw: offer
    sys.argv = ["phosphor-migrate"] + list(argv)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = migrate.main()
    finally:
        init.yes, init.pick, sys.argv = real_yes, real_pick, real_argv
    return rc, buf.getvalue()

open(p, "w").write(OLD)
rc, out = run("--dry-run")
check("--dry-run shows the steps", rc == 0 and "DECK tab in one pane" in out and "+version" in out)
check("--dry-run writes nothing", open(p).read() == OLD and not os.path.exists(p + ".bak"))
check("pending() sees both", len(migrate.pending()) == 2)
rc, out = run(answer=False)
check("no writes nothing", rc == 0 and open(p).read() == OLD)
rc, out = run()
check("yes writes it", rc == 0 and open(p).read() == migrate.plan(OLD)[1])
check("...with the old one as the backup", open(p + ".bak").read() == OLD)
check("...and nothing is pending after", migrate.pending() == [])
rc, out = run()
check("a second run has no step, only the offer again", rc == 0 and "+version" not in out and "new: sys-cards" in out)

# the offers: sys-cards on a profile whose fleet tab has no row of cards
cur = open(p).read()
check("offered() sees sys-cards", len(migrate.offered()) == 1)
rc, out = run("--dry-run", offer=0)
check("--dry-run shows the offer, writes nothing", rc == 0 and "new: sys-cards" in out and open(p).read() == cur)
rc, out = run(offer=2)
check("later: nothing written", rc == 0 and open(p).read() == cur)
rc, out = run(offer=1)
check("no: [deck] declined", migrate.declined(deckconf.tomllib.loads(open(p).read())) == ["sys-cards"])
check("...and the tabs untouched", deckconf.tomllib.loads(open(p).read())["tabs"] == deckconf.tomllib.loads(cur)["tabs"])
rc, out = run()
check("...and never offered again", rc == 0 and "up to date" in out and migrate.offered() == [])
open(p, "w").write(cur)
rc, out = run(offer=0)
sys_tab = next(t for t in deckconf.tomllib.loads(open(p).read())["tabs"] if t["name"] == "SYS")
check("yes: the cards on top of SYS, in rows", sys_tab.get("split") == "rows" and "dash" in sys_tab["panes"][0]
      and sys_tab["panes"][1] == {"cmd": "phosphor fleet"})
rc, out = run()
check("...and then up to date", "up to date" in out)
open(p, "w").write(OLD)
rc, out = run(offer=0)
check("an older profile: the steps and the offer in one write",
      migrate.plan(open(p).read())[0] == [] and migrate.offered() == [] and open(p + ".bak").read() == OLD)

# every shape init writes has no offer pending, and without the row of
# cards gets it back exactly as init writes it
hosts = [{"name": "db-box", "role": "brain", "local": True}, {"name": "nimbus", "role": "work", "ssh": "nimbus"}]
for shape in init.SHAPES:
    for web, tun in ((False, ()), (True, ("relay",))):
        txt = init.render(hosts, "p31", None, web=web, tun=tun, shape=shape)
        bare = "\n".join(l for l in txt.split("\n") if "dash = " not in l)
        got = migrate.sys_cards(bare)
        check("%s: no offer pending" % shape, migrate.offers(txt) == [])
        check("%s without its cards: sys-cards offered" % shape, [i for i, _, _ in migrate.offers(bare)] == ["sys-cards"])
        check("%s (web=%s): the offer gives back init's SYS" % (shape, web),
              deckconf.tomllib.loads(got)["tabs"] == deckconf.tomllib.loads(txt)["tabs"])
# a SYS split in columns keeps them, under the cards
cols = '[[tabs]]\nname = "SYS"\nsplit = "cols"\npanes = [ { cmd = "phosphor fleet" }, { cmd = "btop" } ]\n'
t = deckconf.tomllib.loads(migrate.sys_cards(cols))["tabs"][0]
check("a SYS in columns: rows, the columns kept under the cards",
      t["split"] == "rows" and t["panes"][1] == {"split": "cols", "panes": [{"cmd": "phosphor fleet"}, {"cmd": "btop"}]})
check("no fleet tab: nothing offered", migrate.offers('[[tabs]]\nname = "X"\npanes = [ { cmd = "btop" } ]\n') == [])

open(p, "w").write(newer)
rc, out = run()
check("a newer profile: refused, untouched", rc == 1 and "newer" in out and open(p).read() == newer)
check("...and newer() says so", migrate.newer() == migrate.CURRENT + 1)

# update says so only when something is pending
import update
def offered(text):
    open(p, "w").write(text)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        update.offer_migrate()
    return buf.getvalue()
check("update points at migrate for an older shape", "phosphor migrate" in offered(OLD))
check("...not for one with nothing to change", offered('[deck]\nsession = "deck"\n') == "")
check("update names an offer", "row of cards" in offered('[deck]\nversion = %d\n\n' % migrate.CURRENT
                                                         + '[[tabs]]\nname = "SYS"\npanes = [ { cmd = "phosphor fleet" } ]\n'))

# the DECK tab: P only while there's something to migrate
import panel
st = {"session": "deck", "web": False, "web_local": False, "web_mismatch": False, "screens": None,
      "timer": True, "tunnels": [], "dirty_workspaces": 0, "profile_changed": False,
      "restart_pending": False, "version": "1.0.0", "channel": "stable", "news": [], "migrate": 0}
plain = lambda s: deckconf.re.sub(r"\x1b\[[0-9;]*m", "", s)
keys_of = lambda hit: [k for s in hit.values() for _, _, k in s]
lines, hit, _ = panel.draw({}, dict(st, migrate=2), 100, 30)
check("the deck card offers P", deckconf.re.search(r"P! profile migrate +2 steps  phosphor migrate", "\n".join(map(plain, lines))) and "P" in keys_of(hit))
check("without it, no P", "P" not in keys_of(panel.draw({}, st, 100, 30)[1]))
lines, hit, _ = panel.draw({}, dict(st, offers=1), 100, 30)
check("an offer alone: P, not a warning", deckconf.re.search(r"P  profile migrate +1 new", "\n".join(map(plain, lines))) and "P" in keys_of(hit))

if fails:
    print("migrate-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("migrate-check ok")
