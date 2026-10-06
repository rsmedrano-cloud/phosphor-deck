#!/usr/bin/env python3
"""A misspelled or misplaced key in the profile is said, not ignored
(lib/profcheck.py):

- `thme`, `[tts] enable`, `theme = "p1"`, `web = "true"`, a key above
  every table, an unknown [table]: each is a finding, with a guess;
- what Phosphor writes itself (profiles/*.toml, every shape `phosphor
  init` renders, recipes/*.toml) has none: no false alarms;
- every key in the manual's tables (doc/manual/profile.md) is known, and
  every known key is in the manual;
- `phosphor gen --dry-run` shows them, under a profile of its own.

    python3 tests/profile-schema-check.py
"""
import glob, os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import profcheck
try:
    import tomllib
except ImportError:
    import tomli as tomllib

fails = []
def check(what, ok, got=""):
    if not ok: fails.append(what + ("\n      got: %s" % (got,) if got else ""))

# 1. what's wrong is found, with a guess
BAD = '''
thme = "p3"
[deck]
thme = "p3"
theme = "p1"
web = "true"
[tts]
enable = true
[[hosts]]
name = "nimbus"
rol = "work"
[[tabs]]
name = "SYS"
panes = [ { cmd = "btop", sise = 3, split = "rows", panes = [ { cdw = "/" } ] } ]
[screens.phone]
grahps = "blocks"
[[tunnels]]
host = "db-box"
conf = "x"
[[ci.pipelines]]
name = "web"
provider = "gitea"
[comms]
app = "x"
'''
got = profcheck.problems(tomllib.loads(BAD))
for want in [("profile", "thme is above every [table]: theme in [deck]?"),
             ("[deck]", "unknown key thme: theme?"),
             ("[deck]", 'theme = "p1" isn\'t one of p31, p3, p4, ega, paper'),
             ("[deck]", 'web is true or false, not "true"'),
             ("[tts]", "unknown key enable: enabled?"),
             ("[[hosts]] nimbus", "unknown key rol: role?"),
             ("[[tabs]] SYS", "unknown key sise: size?"),
             ("[[tabs]] SYS", "unknown key cdw: cwd?"),
             ("[screens.phone]", "unknown key grahps: graphs?"),
             ("[[tunnels]] db-box", "unknown key conf: config?"),
             ("[[ci.pipelines]] web", 'provider = "gitea" isn\'t one of github, gitlab'),
             ("[comms]", "unknown table")]:
    check("found: %s %s" % want, want in got, got)
check("nothing else", len(got) == 12, got)

# 2. no false alarms on what Phosphor writes itself
for p in sorted(glob.glob(os.path.join(ROOT, "profiles/*.toml"))):
    got = profcheck.problems(tomllib.load(open(p, "rb")))
    check("%s is clean" % os.path.basename(p), not got, got)
import init
for shape in init.SHAPES:
    for comms in (None, "iamb"):
        txt = init.render([{"name": "box", "role": "brain", "local": True}], "p3", comms, "auto",
                          True, ("db-box",), "nano", "bash", "~/vault", shape)
        got = profcheck.problems(tomllib.loads(txt))
        check("init's %s shape is clean" % shape, not got, got)
for p in sorted(glob.glob(os.path.join(ROOT, "recipes/*.toml"))):
    got = []
    profcheck.tabs("tabs", tomllib.load(open(p, "rb")).get("tabs", []), got)
    check("recipe %s is clean" % os.path.basename(p), not got, got)

# 3. the manual and the schema name the same keys
SECTION = {"[deck]": profcheck.DECK, "[[hosts]]": profcheck.HOST, "[[tabs]]": profcheck.PANE,
           "[[tunnels]]": profcheck.TUNNEL, "[screens]": profcheck.SCREEN}
SECTION.update({"[%s]" % k: v for k, v in profcheck.TABLES.items() if k != "deck"})
NESTED = {"[prometheus]": profcheck.GAUGE, "[ci]": profcheck.PIPELINE}
INHERITED = {"tts", "name", "panes", "split", "gauges", "pipelines"}   # old, or said in prose
text, cur, body = open(os.path.join(ROOT, "doc/manual/profile.md")).read(), None, {}
for line in text.splitlines():
    m = re.match(r"^##+ (.*)", line)
    if m:
        cur = m.group(1).strip() if m.group(1).strip() in SECTION else None
        continue
    if not cur: continue
    body[cur] = body.get(cur, "") + line + "\n"
    m = re.match(r"^\| ([a-z_]+) \|", line)
    if m and m.group(1) != "key":
        check("manual %s: %s is known" % (cur, m.group(1)), m.group(1) in SECTION[cur])
    m = re.match(r"^    ([a-z_]+)\s*=", line)
    if m:
        known = dict(SECTION[cur], **NESTED.get(cur, {}))
        check("manual %s example: %s is known" % (cur, m.group(1)), m.group(1) in known)
for sec, known in list(SECTION.items()) + list(NESTED.items()):
    for k in known:
        if k in INHERITED: continue
        check("%s %s is in the manual" % (sec, k),
              re.search(r"(\| %s \||^    %s\s*=)" % (k, k), body.get(sec, ""), re.M))

# 4. gen shows them, on a throwaway profile
HOME = tempfile.mkdtemp(prefix="schema-")
PROF = os.path.join(HOME, "deck.toml")
open(PROF, "w").write('[deck]\nsession = "probe"\nthme = "p3"\n\n'
                      '[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n')
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
ENV.update(HOME=HOME, PHOSPHOR_PROFILE=PROF, PHOSPHOR_CACHE=os.path.join(HOME, ".cache/phosphor"),
           XDG_CACHE_HOME=os.path.join(HOME, ".cache"), TERM="xterm-256color")
out = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "gen", "--dry-run"],
                     env=ENV, capture_output=True, text=True).stdout
check("gen --dry-run says it", "unknown key thme: theme?" in out, out[-1200:])

if fails:
    print("FAIL"); [print("  - " + f) for f in fails]; sys.exit(1)
print("ok")
