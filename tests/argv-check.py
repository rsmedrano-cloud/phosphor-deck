#!/usr/bin/env python3
"""A flag a command doesn't take is a usage error, and no real call is one.

    python3 tests/argv-check.py

The dispatcher refuses `phosphor CMD --flag` when share/commands.json
doesn't list --flag for CMD (lib/cli.py check()). This holds both sides:

- every command refuses a made-up flag, exit 2 with its usage, and runs
  nothing: `phosphor note --kidn idea hi` writes no note;
- every way phosphor calls itself (layouts, keys, menus: the quoted
  argv lists in lib/ and the dispatcher) and every example in the docs
  passes the check, so the deck never refuses its own panes.
"""
import glob, os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli
bad = []

# 1. a made-up flag, every command (hidden ones are never refused)
for name, e in cli.entries(hidden=True).items():
    for n in [name] + e.get("aliases", []):
        got = cli.check(n, ["--no-such-flag"])
        if e.get("hidden"):
            if got:
                bad.append("hidden `%s` refused a flag: it must never print" % n)
        elif got != "--no-such-flag":
            bad.append("`phosphor %s --no-such-flag` isn't refused" % n)

# the rules: values, `--`, free text, --flag=value
cases = [
    ("note", ["--kind", "idea", "ls", "-la", "here"], None),
    ("note", ["--kidn", "idea", "hi"], "--kidn"),
    ("note", ["--book", "--weird-name", "hi"], None),
    ("ask", ["what", "does", "grep", "--color", "do"], None),
    ("broadcast", ["--host", "db-box", "--", "df", "-h"], None),
    ("broadcast", ["--hots", "db-box", "--", "df"], "--hots"),
    ("attach", ["--screen=phone"], None),
    ("attach", ["--scren=phone"], "--scren=phone"),
    ("fleet", ["-"], None),
    ("workspace", ["new", "idea", "--shape", "solo"], None),
    ("workspace", ["new", "idea", "--shap", "solo"], "--shap"),
]
for cmd, argv, want in cases:
    got = cli.check(cmd, argv)
    if got != want:
        bad.append("check(%s, %s) = %r, want %r" % (cmd, argv, got, want))

# 2. through the dispatcher: exit 2, the usage, nothing run
with tempfile.TemporaryDirectory() as home:
    env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
               XDG_DATA_HOME=os.path.join(home, ".local/share"))
    for k in [k for k in env if k.startswith("ZELLIJ")]:
        del env[k]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "note", "--kidn", "idea", "hi"],
                       env=env, capture_output=True, text=True, timeout=30)
    if r.returncode != 2 or "unknown option --kidn" not in r.stderr or "usage: phosphor note" not in r.stderr:
        bad.append("note --kidn: rc %d, stderr %r" % (r.returncode, r.stderr[-200:]))
    written = [p for p in glob.glob(os.path.join(home, "**"), recursive=True) if os.path.isfile(p)]
    if any("NOTES" in os.path.basename(p) for p in written):
        bad.append("note --kidn still wrote a note: %s" % written)

# 3. phosphor's own calls: ["phosphor"|PHOSPHOR|P(, "cmd", "--flag", ...]
def words(src):
    for m in re.finditer(r'(?:"phosphor"|PHOSPHOR|\bP\()\s*,?\s*((?:"[^"\n]*"\s*,?\s*)+)', src):
        yield re.findall(r'"([^"\n]*)"', m.group(1))
srcs = glob.glob(os.path.join(ROOT, "lib", "*.py")) + [os.path.join(ROOT, "phosphor")]
for f in srcs:
    for w in words(open(f).read()):
        if w and w[0] in ("run",) and len(w) == 1:
            continue
        cmd, rest = w[0], [x for x in w[1:]]
        got = cli.check(cmd, rest) if cli.get(cmd) else None
        if got:
            bad.append("%s calls `phosphor %s`, which refuses %s" % (os.path.relpath(f, ROOT), " ".join(w), got))

# 4. `phosphor CMD --flag ...` written out: the docs' examples, and the
# command lines in code, keys, profiles and recipes (`exec phosphor new --here`)
docs = glob.glob(os.path.join(ROOT, "doc/manual/*.md")) + [os.path.join(ROOT, f) for f in ("README.md", "AGENTS.md")]
docs += srcs + glob.glob(os.path.join(ROOT, "share/*.json")) + glob.glob(os.path.join(ROOT, "share/*.kdl")) + glob.glob(os.path.join(ROOT, "profiles/*.toml")) \
    + glob.glob(os.path.join(ROOT, "recipes/**/*"), recursive=True)
docs = [f for f in docs if os.path.isfile(f) and not f.endswith("commands.json")]
for f in docs:
    for line in open(f):
        # shortcuts' keys: RUN % ("new --here", "NEW") is `phosphor new --here`
        line = re.sub(r'RUN % \("', "phosphor ", line)
        for m in re.finditer(r"phosphor\\?\"? ([a-z][a-z-]*)((?: +[^\s`|;()#·\[\]\"',]+)*)", line):
            cmd, rest = m.group(1), m.group(2).split()
            if not cli.get(cmd):
                continue
            # placeholders and prose after the call: stop at the first word that isn't a flag or a value
            got = cli.check(cmd, rest)
            if got:
                bad.append("%s: `phosphor %s %s` is refused (%s)" % (os.path.relpath(f, ROOT), cmd, " ".join(rest), got))

if bad:
    print("\n".join(bad)); sys.exit(1)
print("argv-check ok")
