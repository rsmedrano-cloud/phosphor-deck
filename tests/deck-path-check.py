#!/usr/bin/env python3
"""The deck's panes see your PATH: gen writes it into the deck unit, merged
with what the unit had (a gen from a poor environment never shrinks it),
~/.local/bin first; doctor says what a pane lacks that a login shell has.

    python3 tests/deck-path-check.py

A throwaway HOME and runtime dir; only gen --dry-run, nothing reaches a deck.
"""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

home = tempfile.mkdtemp()
os.environ.update(HOME=home, XDG_RUNTIME_DIR=tempfile.mkdtemp())
for v in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "PHOSPHOR_DATA", "PHOSPHOR_CACHE", "PHOSPHOR_NOTES", "VIRTUAL_ENV"):
    os.environ.pop(v, None)
for d in (".config/phosphor", ".local/bin", ".cargo/bin", "go/bin", "venv/bin"):
    os.makedirs(os.path.join(home, d))
open(os.path.join(home, ".config/phosphor/deck.toml"), "w").write('''[deck]
session = "path-check-none"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "AI"
panes = [ { cmd = "bash" } ]
''')
BIN, CARGO, GO, VENV = (os.path.join(home, d) for d in (".local/bin", ".cargo/bin", "go/bin", "venv/bin"))

import deckconf, doctor, gen
from ui import OK, WARN
prof = deckconf.load()[0]

# the PATH gen runs in, cleaned: relative, missing, repeated, a venv's bin, % and "
env = {"PATH": ":".join([CARGO, "rel/bin", "/no/such/dir", CARGO + "/", VENV, home + "/100%",
                         "/usr/bin", "/bin"]), "VIRTUAL_ENV": os.path.dirname(VENV)}
os.makedirs(home + "/100%")
p = gen.deck_path(None, env).split(":")
need("~/.local/bin first: %s" % p, p[0] == BIN)
need("the shell's own entries next, in its order", p[1:4] == [CARGO, "/usr/bin", "/bin"])
need("relative and missing entries go", "rel/bin" not in p and "/no/such/dir" not in p)
need("no repeats", len(p) == len(set(p)))
need("the virtualenv's bin goes", VENV not in p)
need("what the unit line can't hold goes", not any("%" in d for d in p))
need("systemd's own stay", "/usr/sbin" in p or not os.path.isdir("/usr/sbin"))

# a gen from a poor environment keeps what the unit had
poor = gen.deck_path(":".join(p + [GO]), {"PATH": "/usr/bin:/bin"}).split(":")
need("never shrinks: %s" % poor, CARGO in poor and GO in poor and poor[0] == BIN)
gone = gen.deck_path("/no/longer/here:" + CARGO, {"PATH": "/usr/bin"}).split(":")
need("an old entry that's gone is dropped", "/no/longer/here" not in gone)

# the unit carries it, and reads back
os.environ["PATH"] = CARGO + ":" + os.environ.get("PATH", "/usr/bin:/bin")
unit = gen.units(gen.Ctx(prof))["path-check-none.service"]
up = gen.unit_path(unit)
need("the unit sets PATH", up is not None and up.split(":")[:2] == [BIN, CARGO])
need("a unit from before has none", gen.unit_path("[Service]\nEnvironment=TERM=x\n") is None)

# gen --dry-run says what the panes gain, and writes nothing
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "gen", "--dry-run"],
                   capture_output=True, text=True, timeout=60)
need("gen --dry-run names the PATH: %s" % r.stdout[-400:], "would add ~/.local/bin" in r.stdout)
need("--dry-run writes no unit", not os.path.exists(os.path.join(gen.UDIR, "path-check-none.service")))

# doctor: what a pane lacks that a login shell has
st, val, _ = doctor.panes_path("[Service]\nEnvironment=TERM=x\n", "/usr/bin")
need("doctor: a unit without PATH warns", st == WARN and "systemd" in val)
st, val, _ = doctor.panes_path(unit, ":".join([GO, BIN, "/usr/bin"]))
need("doctor: names what's missing: %s" % val, st == WARN and "~/go/bin" in val and ".local" not in val)
st, val, _ = doctor.panes_path(unit, ":".join([CARGO, BIN, "/no/such/dir"]))
need("doctor: all there is OK: %s" % val, st == OK)
st, _, _ = doctor.panes_path(unit, None)
need("doctor: an unreadable login shell isn't a warning", st == OK)

if fails:
    print("FAIL: " + "; ".join(fails)); sys.exit(1)
print("ok: the deck's panes get your PATH")
