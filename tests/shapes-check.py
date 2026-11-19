#!/usr/bin/env python3
"""The shapes init writes, reduced to their structure (each tab, each
pane's command, the cards, the top-level tables), against
tests/shapes.json. A change to a shape never reaches a profile that
already exists: a new element fails here until it has its way there (an
offer or a step in lib/migrate.py, checked by tests/migrate-check.py) and
the snapshot is updated on purpose. Text-only changes to init.py (a
comment, a size) stay quiet.

    python3 tests/shapes-check.py            # check
    python3 tests/shapes-check.py --update   # after adding the offer or step
    python3 tests/shapes-check.py --update --no-offer   # a change no profile needs

The offers and the profile version are part of the snapshot too: an offer
that goes away (profiles that took or declined it lose track) or a version
that goes back fails, and --update refuses a changed shape when
lib/migrate.py has neither a new offer nor a new step, unless --no-offer
says it on purpose (an element removed, a fix existing profiles don't need).
"""
import json, os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import deckconf, init, migrate

SNAP = os.path.join(REPO, "tests", "shapes.json")
# fixed answers: a brain and a work machine, a chat, web and a tunnel,
# fixed cards (sys_cards() depends on who's signed in)
HOSTS = [{"name": "db-box", "role": "brain", "local": True}, {"name": "nimbus", "role": "work", "ssh": "nimbus"}]

def pane(p):
    if "dash" in p:
        return "dash: " + " ".join(p["dash"])
    if "panes" in p:
        return [pane(q) for q in p["panes"]]
    if "ssh" in p:
        return "ssh " + p["ssh"]
    return " ".join([p.get("cmd", "?")] + [str(a) for a in p.get("args", [])])

def structure(shape):
    txt = init.render(HOSTS, "p31", "weechat", web=True, tun=("relay",), shape=shape,
                      cards=["version", "screens", "web", "tunnel"])
    prof = deckconf.tomllib.loads(txt)
    return {"tables": sorted(prof),
            "deck": sorted(prof.get("deck", {})),
            "tabs": [[t["name"], [pane(p) for p in t.get("panes", [])]] for t in prof.get("tabs", [])]}

now = {"shapes": {s: structure(s) for s in init.SHAPES}, "offers": [i for i, _, _ in migrate.OFFERS],
       "version": migrate.CURRENT}
was = json.load(open(SNAP))
shapes_changed = now["shapes"] != was["shapes"]
gone = [o for o in was["offers"] if o not in now["offers"]]
added = [o for o in now["offers"] if o not in was["offers"]]
offer_fails = ["offer %s is gone from lib/migrate.py: profiles that took or declined it lose track" % o
               for o in gone]
if now["version"] < was["version"]:
    offer_fails.append("the profile version went back: %s -> %s" % (was["version"], now["version"]))
if "--update" in sys.argv:
    if offer_fails:
        print("shapes-check: not updated\n  " + "\n  ".join(offer_fails)); sys.exit(1)
    if shapes_changed and not added and now["version"] == was["version"] and "--no-offer" not in sys.argv:
        print("shapes-check: not updated: a shape changed, and lib/migrate.py has no new offer and no new step,\n"
              "  so a profile that already exists never gets it. Add one (and its check in tests/migrate-check.py),\n"
              "  or say no profile needs it: python3 tests/shapes-check.py --update --no-offer")
        sys.exit(1)
    json.dump(now, open(SNAP, "w"), indent=1); open(SNAP, "a").write("\n")
    print("shapes-check: tests/shapes.json updated"); sys.exit(0)
fails = list(offer_fails)
if not offer_fails and (added or now["version"] != was["version"]):
    fails.append("lib/migrate.py changed (offers %s, version %s -> %s) but tests/shapes.json didn't"
                 % (added or "the same", was["version"], now["version"]))
for s in sorted(set(now["shapes"]) | set(was["shapes"])):
    a, b = was["shapes"].get(s), now["shapes"].get(s)
    if a == b:
        continue
    if a is None or b is None:
        fails.append("shape %s %s" % (s, "is new" if a is None else "is gone")); continue
    for k in ("tables", "deck"):
        if a[k] != b[k]:
            fails.append("%s: %s %s -> %s" % (s, k, a[k], b[k]))
    ta, tb = dict((n, p) for n, p in a["tabs"]), dict((n, p) for n, p in b["tabs"])
    if [n for n, _ in a["tabs"]] != [n for n, _ in b["tabs"]]:
        fails.append("%s: tabs %s -> %s" % (s, [n for n, _ in a["tabs"]], [n for n, _ in b["tabs"]]))
    for n in ta:
        if n in tb and ta[n] != tb[n]:
            fails.append("%s: %s's panes %s -> %s" % (s, n, json.dumps(ta[n]), json.dumps(tb[n])))
if fails:
    print("shapes-check FAILED\n  " + "\n  ".join(fails))
    if shapes_changed:
        print("  a profile that already exists never gets it: add an offer (or a step) in lib/migrate.py,\n"
              "  check it in tests/migrate-check.py, then: python3 tests/shapes-check.py --update")
    sys.exit(1)
print("shapes-check ok")
