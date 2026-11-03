#!/usr/bin/env python3
"""A `deck` command that's running when gen (or a screen's kit) writes a
new one keeps running the old one to its end. bash reads a script as it
goes: rewritten in place, the loop that just ended (a detach) reads on
from its old offset into the new text -- and may run whatever lands
there, another ssh into the deck among them. So gen writes a new file and
renames it over the old (os.replace), keeping the mode, through a link;
the kits do the same with mv.

    python3 tests/script-swap-check.py
"""
import contextlib, io, os, shutil, subprocess, sys, tempfile, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import gen, phone

_write = gen.write
def quiet(*a):
    with contextlib.redirect_stdout(io.StringIO()):
        return _write(*a)
gen.write = quiet

fails = []
def check(what, ok):
    if not ok: fails.append(what)

d = tempfile.mkdtemp()
deck = os.path.join(d, "deck")
old = "#!/bin/sh\nwhile :; do sleep 1; break; done\n"
# what bash would read next if the file changed under it: a command right
# at the offset where the old script ended
new = "#" * (len(old) - 1) + "\necho LEAKED\n"
gen.write(deck, old, False, [])
os.chmod(deck, 0o755)

bash = shutil.which("bash")
if bash:
    p = subprocess.Popen([bash, deck], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.3)                      # inside the loop's sleep
    gen.write(deck, new, False, [])
    out = p.communicate(timeout=10)[0]
    check("a running deck doesn't read on into the one gen just wrote (got %r)" % out, "LEAKED" not in out)
check("the new command is there", open(deck).read() == new)
check("...and still executable", os.stat(deck).st_mode & 0o777 == 0o755)
check("no temp file left beside it", sorted(os.listdir(d)) == ["deck"])

# a generated file the user keeps as a link to their dotfiles stays a link
real = os.path.join(d, "dotfiles-deck")
link = os.path.join(d, "linked")
open(real, "w").write(old); os.symlink(real, link)
gen.write(link, new, False, [])
check("a link stays a link", os.path.islink(link) and open(real).read() == new)

check("dry-run writes nothing", gen.write(deck, old, True, []) is None and open(deck).read() == new)

# the kits: the deck command is written beside, then moved over
for name, kit in (("phone kit", phone.SCRIPT), ("screen kit", phone.POSIX_SCRIPT)):
    check("the %s writes the deck command beside it and moves it over" % name,
          'cat > "$B/deck" <<EOF' not in kit and 'cat > "$PREFIX/bin/deck" <<EOF' not in kit
          and ("deck.new" in kit and 'mv "' in kit))

shutil.rmtree(d)
if fails:
    for f in fails: print("FAIL:", f)
    sys.exit(1)
print("ok: a running deck command keeps its own copy when a new one is written")
