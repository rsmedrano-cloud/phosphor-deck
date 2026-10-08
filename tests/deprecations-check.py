#!/usr/bin/env python3
"""What's deprecated says so, and goes away when it said it would.

    python3 tests/deprecations-check.py

share/deprecations.json lists the public things on their way out
(doc/manual/api.md): a command, a flag, a profile key. This holds:

- every entry names something that exists, with a `since` and a `remove`
  at least one minor later, and the suite fails once VERSION reaches
  `remove`: the policy is kept by the pipeline, not by memory;
- a deprecated command or flag still runs, and warns on stderr only, so
  `--json` stays one clean object; `--help` and `phosphor help` say so,
  completion stops offering it; an alias can go without its command;
- a deprecated profile key is still read, and gen and doctor say so.
"""
import json, os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli, profcheck
bad = []

def ver(s):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(map(int, m.groups())) if m else None

# 1. the real file
VERSION = ver(open(os.path.join(ROOT, "VERSION")).read().strip())
for d in cli.deprecations():
    label = "%s %s" % (d.get("kind"), d.get("name"))
    for k in ("kind", "name", "since", "remove", "use"):
        if not d.get(k):
            bad.append("%s: no %s" % (label, k))
    since, remove = ver(d.get("since")), ver(d.get("remove"))
    if not since or not remove:
        bad.append("%s: since/remove aren't X.Y.Z" % label); continue
    if remove[:2] <= since[:2]:
        bad.append("%s: remove %s isn't a later minor than since %s" % (label, d["remove"], d["since"]))
    if VERSION >= remove:
        bad.append("%s was due to go in %s: remove it now (doc/manual/api.md)" % (label, d["remove"]))
    kind = d["kind"]
    if kind == "command":
        if not cli.get(d["name"]):
            bad.append("%s: no such command or alias" % label)
    elif kind == "flag":
        e = cli.get(d.get("command") or "")
        if not e or d["name"] not in e.get("options", []) + e.get("internal", []):
            bad.append("%s: %s doesn't take it" % (label, d.get("command")))
    elif kind == "key":
        known = profcheck.TABLES.get(d.get("table"), {})
        if d["name"] not in known:
            bad.append("%s: [%s] has no such key in lib/profcheck.py" % (label, d.get("table")))
    else:
        bad.append("%s: kind is command, flag or key" % label)

# the manual's list is the file's
api = open(os.path.join(ROOT, "doc/manual/api.md")).read()
for d in cli.deprecations():
    if not re.search(r"`[^`]*%s[^`]*`, since %s, goes in %s" % (re.escape(d["name"]), re.escape(d["since"]),
                                                                  re.escape(d["remove"])), api):
        bad.append("doc/manual/api.md doesn't list %s (since %s, goes in %s)" % (d["name"], d["since"], d["remove"]))

# the real key still warns, and is still read
for d in cli.deprecations("key"):
    got = profcheck.problems({d["table"]: {d["name"]: True}})
    if ("[%s]" % d["table"], cli.warning(d)) not in got:
        bad.append("profcheck doesn't warn about %s: %s" % (d["name"], got))

# 2. made-up ones: an alias, a command, a flag
fake = {"deprecated": [
    {"kind": "command", "name": "deck", "since": "1.9.2", "remove": "2.1.0", "use": "phosphor attach"},
    {"kind": "command", "name": "version", "since": "1.9.2", "remove": "2.1.0", "use": "something else"},
    {"kind": "flag", "command": "version", "name": "--notes", "since": "1.9.2", "remove": "2.1.0", "use": "--news"},
]}
with tempfile.TemporaryDirectory() as home:
    path = os.path.join(home, "deprecations.json")
    json.dump(fake, open(path, "w"))
    cli.DEPRECATIONS, cli._gone = path, None

    if cli.deprecated("attach", []):
        bad.append("attach warns when only its alias deck is deprecated")
    if len(cli.deprecated("deck", [])) != 1:
        bad.append("deck (deprecated alias) doesn't warn once: %s" % cli.deprecated("deck", []))
    got = cli.deprecated("version", ["--notes", "--json"])
    if len(got) != 2 or not any("--notes" in w for w in got):
        bad.append("version --notes: %s" % got)
    if any("--notes" in w for w in cli.deprecated("version", ["--", "--notes"])):
        bad.append("a --notes after -- warns")
    after, _ = cli.completions()
    if "deck" in after or "attach" not in after:
        bad.append("completion still offers deck, or lost attach")
    if "version" in after:
        bad.append("completion still offers a deprecated command")
    if cli.get("version")["summary"] + " (deprecated)" not in " ".join(cli.usage_text().split()):
        bad.append("phosphor help doesn't mark version deprecated")

    # through the dispatcher: it runs, stdout is still JSON, stderr warns
    env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
               XDG_DATA_HOME=os.path.join(home, ".local/share"), PHOSPHOR_DEPRECATIONS=path)
    for k in [k for k in env if k.startswith("ZELLIJ")]:
        del env[k]
    P = [sys.executable, os.path.join(ROOT, "phosphor")]
    r = subprocess.run(P + ["version", "--json"], env=env, capture_output=True, text=True, timeout=30)
    try:
        json.loads(r.stdout)
    except ValueError:
        bad.append("version --json isn't clean JSON with a warning: %r" % r.stdout[:200])
    if r.returncode != 0 or "phosphor: version is deprecated since 1.9.2" not in r.stderr:
        bad.append("version --json: rc %d, stderr %r" % (r.returncode, r.stderr[-200:]))
    r = subprocess.run(P + ["version", "--help"], env=env, capture_output=True, text=True, timeout=30)
    if "--notes is deprecated" not in r.stdout or "version is deprecated" not in r.stdout:
        bad.append("version --help doesn't say what's deprecated: %r" % r.stdout[-300:])

if bad:
    print("\n".join(bad)); sys.exit(1)
print("deprecations-check ok")
