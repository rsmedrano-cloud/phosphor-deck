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
if "--update" in sys.argv:
    json.dump(now, open(SNAP, "w"), indent=1); open(SNAP, "a").write("\n")
    print("shapes-check: tests/shapes.json updated"); sys.exit(0)
was = json.load(open(SNAP))
fails = []
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
    print("shapes-check FAILED: a shape changed\n  " + "\n  ".join(fails))
    print("  a profile that already exists never gets it: add an offer (or a step) in lib/migrate.py,\n"
          "  check it in tests/migrate-check.py, then: python3 tests/shapes-check.py --update")
    sys.exit(1)
print("shapes-check ok")
