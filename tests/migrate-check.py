#!/usr/bin/env python3
"""phosphor migrate: an older profile gets each pending step (the DECK tab
in one pane, [deck] tts into [tts] enabled) and version = CURRENT, through
write_profile with a .bak; an up-to-date or newer profile is left alone; a
profile init writes is already current; doctor, gen, update and the DECK
tab only speak up when there's something to change.

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
def run(*argv, answer=True):
    real_yes, real_argv = init.yes, sys.argv
    init.yes = lambda *a, **kw: answer
    sys.argv = ["phosphor-migrate"] + list(argv)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = migrate.main()
    finally:
        init.yes, sys.argv = real_yes, real_argv
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
check("a second run says up to date", rc == 0 and "up to date" in out)

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

# the DECK tab: P only while there's something to migrate
import panel
st = {"session": "deck", "web": False, "web_local": False, "web_mismatch": False, "screens": None,
      "timer": True, "tunnels": [], "dirty_workspaces": 0, "profile_changed": False,
      "restart_pending": False, "version": "1.0.0", "channel": "stable", "news": [], "migrate": 0}
plain = lambda s: deckconf.re.sub(r"\x1b\[[0-9;]*m", "", s)
keys_of = lambda hit: [k for s in hit.values() for _, _, k in s]
lines, hit, _ = panel.draw({}, dict(st, migrate=2), 100, 30)
check("the deck card offers P", "profile: 2 to migrate" in "".join(map(plain, lines)) and "P" in keys_of(hit))
check("without it, no P", "P" not in keys_of(panel.draw({}, st, 100, 30)[1]))

if fails:
    print("migrate-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("migrate-check ok")
