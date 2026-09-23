#!/usr/bin/env python3
"""Notes in your own vault (#22): the profile's [notes] folder, migration,
the vault picker's folder-finding, and setup's text surgery.

    python3 tests/notes-vault-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
vault = os.path.join(tmp, "vault")
os.makedirs(vault)
profile = os.path.join(tmp, "deck.toml")
open(profile, "w").write('[notes]\nfolder = "%s"\n' % vault)
os.environ["PHOSPHOR_PROFILE"] = profile

import notes

check("notes_dir() follows the profile", notes.notes_dir() == vault)
check("the default PATH lands inside it", notes.PATH == os.path.join(vault, "notes.md"))

argv = ["--book", "work"]
notes.use_book(argv)
check("--book stays inside the same vault", notes.PATH == os.path.join(vault, "work.md"))
check("--book still names the book", notes.BOOK == "WORK NOTES")

# -- migrate: moves, never overwrites, moves the archive alongside it --
old = os.path.join(tmp, "old-notes.md")
open(old, "w").write("# mine\n")
open(old.replace(".md", "-archive.md"), "w").write("# archived\n")
new = os.path.join(vault, "notes.md")
moved = notes.migrate(old, new)
check("the notebook moved", sorted(moved) == ["notes-archive.md", "notes.md"])
check("its content came with it", open(new).read() == "# mine\n")
check("the old file is gone", not os.path.exists(old))

open(old, "w").write("# a second one\n")
moved2 = notes.migrate(old, new)
check("migrate refuses to overwrite an existing notebook", moved2 == [] and os.path.exists(old))

# -- vault_candidates: only folders that actually have .obsidian/ --
obs = os.path.join(tmp, "Documents", "MyVault")
os.makedirs(os.path.join(obs, ".obsidian"))
os.makedirs(os.path.join(tmp, "Documents", "NotAVault"))
cands = notes.vault_candidates()
check("finds the real vault", obs in cands)
check("skips a plain folder", os.path.join(tmp, "Documents", "NotAVault") not in cands)

# -- deck_setup: setting and clearing [notes] as text, round-trip --
import deck_setup as ds
base = '[deck]\nsession = "deck"\n\n[[hosts]]\nname = "x"\n\n[[tabs]]\nname = "WORK"\n'
t1 = ds.set_notes_text(base, "/somewhere/vault")
check("adds a [notes] table", "[notes]" in t1 and 'folder = "/somewhere/vault"' in t1)
t2 = ds.set_notes_text(t1, "/somewhere/else")
check("replaces it in place, once", t2.count("[notes]") == 1 and '"/somewhere/else"' in t2)
t3 = ds.remove_notes_text(t2)
check("removing it drops the whole table", "[notes]" not in t3)
check("but leaves the rest of the profile alone", "[[tabs]]" in t3 and 'name = "WORK"' in t3)

# -- doctor: a configured folder that doesn't exist is a warning, not silence --
import doctor, io
prof = {"hosts": [{"name": "x", "role": "brain", "local": True}],
        "notes": {"folder": os.path.join(tmp, "missing-vault")}}
buf, real = io.StringIO(), sys.stdout
sys.stdout = buf
try:
    doctor.run(prof)
finally:
    sys.stdout = real
out = buf.getvalue()
check("doctor names the missing folder", "notes folder" in out and "missing" in out)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
