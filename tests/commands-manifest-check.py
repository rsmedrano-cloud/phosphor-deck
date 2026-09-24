#!/usr/bin/env python3
"""share/commands.json stays in sync with phosphor's own command surface.

    python3 tests/commands-manifest-check.py

- every `phosphor COMMAND` in the USAGE string (the same set docs-check.py
  cross-checks against the manual and README) has a manifest entry, and
  the manifest has no stale entry for a command that no longer exists;
- every entry has the required fields, with the right types.
"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = []

usage = open(os.path.join(ROOT, "phosphor")).read().split('USAGE = """', 1)[1].split('"""', 1)[0]
commands = sorted(set(re.findall(r"^\s*phosphor ([a-z][a-z-]*)", usage, re.M)))

manifest = json.load(open(os.path.join(ROOT, "share/commands.json")))
entries = {k: v for k, v in manifest.items() if not k.startswith("_")}

for c in commands:
    if c not in entries:
        bad.append("share/commands.json is missing `%s` (in USAGE)" % c)
for c in entries:
    if c not in commands:
        bad.append("share/commands.json has `%s`, not a real phosphor command (USAGE doesn't mention it)" % c)

for name, e in entries.items():
    for field, typ in (("mutates", bool), ("needs_deck", bool), ("note", str)):
        if field not in e:
            bad.append("share/commands.json: `%s` is missing `%s`" % (name, field))
        elif not isinstance(e[field], typ):
            bad.append("share/commands.json: `%s.%s` should be %s" % (name, field, typ.__name__))
    if not e.get("note", "").strip():
        bad.append("share/commands.json: `%s.note` is empty" % name)

if bad:
    print("\n".join(bad)); sys.exit(1)
print("commands-manifest-check ok (%d commands)" % len(commands))
