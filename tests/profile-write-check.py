#!/usr/bin/env python3
"""deckconf.write_profile() is the one door the profile goes through: it
writes nothing that doesn't parse or pass its check, nothing over a write
that happened since the caller read the file, and what it writes lands
whole (temp file + os.replace), through a symlink, keeping the mode.

    python3 tests/profile-write-check.py
"""
import glob, os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import deckconf

fails = []
def check(what, ok):
    if not ok: fails.append(what)

d = tempfile.mkdtemp()
p = os.path.join(d, "deck.toml")
v1 = '[deck]\ntheme = "p3"\n'
open(p, "w").write(v1); os.chmod(p, 0o600)

err = deckconf.write_profile('[deck\ntheme = "p1"\n', p=p)
check("a profile that doesn't parse is refused", err and "parse" in err)
check("...and the file is untouched", open(p).read() == v1)
check("...and no backup was made", not os.path.exists(p + ".bak"))

err = deckconf.write_profile('[deck]\ntheme = "p1"\n', lambda prof: prof["deck"]["theme"] == "p7", p=p)
check("a failed check is refused", err and open(p).read() == v1)

err = deckconf.write_profile('[deck]\ntheme = "p1"\n', expect='[deck]\ntheme = "amber"\n', p=p)
check("a write since the caller read it is not undone", err and "meanwhile" in err and open(p).read() == v1)

v2 = '[deck]\ntheme = "p1"\n'
err = deckconf.write_profile(v2, lambda prof: prof["deck"]["theme"] == "p1", expect=v1, p=p)
check("a good write lands: %s" % err, err is None and open(p).read() == v2)
check("the old text is the backup", open(p + ".bak").read() == v1)
check("the mode is kept", os.stat(p).st_mode & 0o777 == 0o600)
check("no temp file left behind", not glob.glob(os.path.join(d, ".deck.toml.*")))

err = deckconf.write_profile('[deck]\ntheme = "p7"\n', p=p, keep=False)
check("keep=False skips the backup", err is None and open(p + ".bak").read() == v1)

# a dotfiles-style symlinked profile stays a symlink
real = os.path.join(d, "dotfiles.toml"); os.rename(p, real); os.symlink(real, p)
err = deckconf.write_profile(v1, p=p)
check("through a symlink: %s" % err, err is None and os.path.islink(p) and open(real).read() == v1)

# the write is a replace, never a truncate in place: a reader holding the
# old file still sees all of it
q = os.path.join(d, "atomic.toml"); open(q, "w").write(v1)
before = os.stat(q).st_ino
deckconf.write_profile(v2, p=q)
check("written by replacing the file, not truncating it", os.stat(q).st_ino != before)

err = deckconf.write_profile(v1, p=deckconf.EXAMPLE)
check("the repo's example is never written", err and "no profile" in err)

# a profile kept 600 (a token in it) gets 600 backups too, whatever the umask
q = os.path.join(d, "secret.toml"); open(q, "w").write(v1); os.chmod(q, 0o600)
old = os.umask(0o022)
deckconf.write_profile(v2, p=q); deckconf.write_profile(v1, p=q)
os.umask(old)
modes = [oct(os.stat(f).st_mode & 0o777) for f in (q, q + ".bak", q + ".bak.2")]
check("backups keep the profile's mode: %s" % modes, modes == ["0o600"] * 3)

err = deckconf.write_profile(v1, p=os.path.join(d, "new", "deck.toml"))
check("a first profile (init) is written, folder and all", err is None)

# no profile writer bypasses the door
for f in glob.glob(os.path.join(REPO, "lib", "*.py")):
    if f.endswith("deckconf.py"): continue
    src = open(f).read()
    check("%s calls deckconf.backup() itself" % os.path.basename(f), "deckconf.backup(" not in src)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
