#!/usr/bin/env python3
"""share/commands.json is the one definition of phosphor's commands, and holds.

    python3 tests/commands-manifest-check.py

phosphor help, CMD --help, the dispatcher, the commands menu and completion
all read it (lib/cli.py), so this checks the definition itself:

- every entry has the required fields with the right types, a category
  from _categories, and only fields _schema explains;
- every command runs: the dispatcher handles it by name, or its module is
  a lib/ file; an alias never shadows another command;
- every flag and word it declares is one its code really reads (a string
  in its module or the dispatcher), so completion never offers a dead one;
- phosphor help and the completion scripts list every command.
"""
import json, os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli
bad = []

manifest = json.load(open(os.path.join(ROOT, "share/commands.json")))
schema, cats = manifest.get("_schema", {}), manifest.get("_categories", [])
entries = cli.entries(hidden=True)
dispatcher = open(os.path.join(ROOT, "phosphor")).read()
# the names phosphor's main() handles itself, before it looks for a module
by_name = set(re.findall(r'cmd == "([a-z-]+)"', dispatcher))
for group in re.findall(r"cmd in \(([^)]*)\)", dispatcher):
    by_name |= set(re.findall(r'"([a-z-]+)"', group))

required = {"category": str, "usage": str, "summary": str, "mutates": bool, "needs_deck": bool, "note": str}
optional = {"options": list, "words": list, "values": dict, "aliases": list, "module": (str, type(None)),
            "own_help": bool, "hidden": bool, "internal": list, "takes_value": list, "free_text": bool}
names = set(entries)
seen_alias = set()
for name, e in entries.items():
    where = "share/commands.json: `%s`" % name
    for field, typ in required.items():
        if field not in e:
            bad.append("%s is missing `%s`" % (where, field))
        elif not isinstance(e[field], typ):
            bad.append("%s.%s should be %s" % (where, field, typ.__name__))
    for field in e:
        if field not in schema:
            bad.append("%s has `%s`, which _schema doesn't explain" % (where, field))
        elif field in optional and not isinstance(e[field], optional[field]):
            bad.append("%s.%s has the wrong type" % (where, field))
    if not str(e.get("note", "")).strip() or not str(e.get("summary", "")).strip():
        bad.append("%s has an empty note or summary" % where)
    if e.get("category") not in cats:
        bad.append("%s.category %r isn't one of _categories" % (where, e.get("category")))
    if not str(e.get("usage", "")).startswith("phosphor " + name):
        bad.append("%s.usage should start with `phosphor %s`" % (where, name))
    for a in e.get("aliases", []):
        if a in names or a in seen_alias:
            bad.append("%s: alias `%s` is already a command or another alias" % (where, a))
        seen_alias.add(a)
    if name not in by_name and not cli.module(name):
        bad.append("%s: nothing runs it (not handled by name in phosphor, no lib/%s.py)"
                   % (where, e.get("module", name)))
    # what it declares, its code reads
    mod = e.get("module", name) or name
    src = dispatcher
    if os.path.exists(os.path.join(ROOT, "lib", mod + ".py")):
        src += open(os.path.join(ROOT, "lib", mod + ".py")).read()
    if name == "screen":
        src += open(os.path.join(ROOT, "lib", "phone.py")).read()
    if name == "attach":
        src += open(os.path.join(ROOT, "lib", "kinds.py")).read()
    if name in ("restore",):
        src += open(os.path.join(ROOT, "lib", "backup.py")).read()
    for w in e.get("options", []) + e.get("internal", []) + [w for w in e.get("words", []) if w != "@topics"] + list(e.get("values", {})):
        if '"%s"' % w not in src and "'%s'" % w not in src:
            bad.append("%s declares `%s`, but its code never reads it" % (where, w))
    for f in e.get("takes_value", []):
        if f not in e.get("options", []) + e.get("internal", []):
            bad.append("%s: takes_value `%s`, which isn't in its options or internal" % (where, f))
    for f in e.get("values", {}):
        if f not in e.get("options", []):
            bad.append("%s: values for `%s`, which isn't in its options" % (where, f))
for c in cats:
    if not any(e.get("category") == c for e in entries.values()):
        bad.append("share/commands.json: category %r has no command" % c)

phosphor = [sys.executable, os.path.join(ROOT, "phosphor")]
env = dict(os.environ, PHOSPHOR_PROFILE=os.path.join(ROOT, "profiles", "example.toml"))
helptext = subprocess.run(phosphor + ["help"], capture_output=True, text=True, env=env).stdout
for name in cli.entries():
    if not re.search(r"^    phosphor %s(\s|$)" % re.escape(name), helptext, re.M):
        bad.append("phosphor help doesn't list `%s`" % name)
for shell in ("bash", "zsh"):
    out = subprocess.run(phosphor + ["completion", shell], capture_output=True, text=True, env=env).stdout
    for name, e in cli.entries().items():
        for n in [name] + e.get("aliases", []):
            if not re.search(r"^\s+%s\) w=" % re.escape(n), out, re.M):
                bad.append("phosphor completion %s doesn't know `%s`" % (shell, n))

if bad:
    print("\n".join(bad)); sys.exit(1)
print("commands-manifest-check ok (%d commands)" % len(entries))
