#!/usr/bin/env python3
"""tests/audit.py with a fake agy: it runs in a clone with no remote, with
no zellij variables and copies of phosphor's data, and its report lands in
the notebook under "audit VERSION (SHA)", which release.py looks for."""
import os, shutil, subprocess, sys, tempfile

if not shutil.which("git"):             # CI's fast job has no git: nothing to clone
    print("skipped: no git"); sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="audit-check-")
bin_, book, seen = os.path.join(tmp, "bin"), os.path.join(tmp, "notes.md"), os.path.join(tmp, "seen")
os.makedirs(bin_)
open(book, "w").write("# Phosphor notes\n\n")
fake = os.path.join(bin_, "agy")
open(fake, "w").write("""#!/bin/sh
{ pwd; git remote | wc -l; env | grep -c '^ZELLIJ'; echo "$PHOSPHOR_NOTES"; echo "$PHOSPHOR_DATA"; } > %s
[ -f AGENTS.md ] || exit 3
echo "# Auditoria de prueba"
echo "1. Bugs: nada"
""" % seen)
os.chmod(fake, 0o755)

env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], PHOSPHOR_NOTES=book,
           ZELLIJ="0", ZELLIJ_SESSION_NAME="deck")
r = subprocess.run([sys.executable, "tests/audit.py", "--timeout", "1", "--ref", "HEAD"], cwd=ROOT, env=env,
                   capture_output=True, text=True)
fails = []
if r.returncode != 0:
    fails.append("exit %d: %s" % (r.returncode, (r.stdout + r.stderr).strip()))
else:
    cwd, remotes, zellij, notes_env, data = open(seen).read().split("\n")[:5]
    if not cwd.startswith(tempfile.gettempdir()) or cwd.startswith(ROOT):
        fails.append("agy ran in %s, not a throwaway clone" % cwd)
    if remotes.strip() != "0": fails.append("the clone still has a remote")
    if zellij.strip() != "0": fails.append("ZELLIJ variables reached agy")
    if notes_env == book or not data.startswith(tempfile.gettempdir()):
        fails.append("agy got the real notebook or data folder")
    if os.path.exists(cwd): fails.append("the scratch clone wasn't removed")
    text = open(book).read()
    if "· summary · agy · audit " not in text or "Auditoria de prueba" not in text:
        fails.append("the report isn't in the notebook: %r" % text[-200:])
    sys.path.insert(0, os.path.join(ROOT, "tests")); sys.path.insert(0, os.path.join(ROOT, "lib"))
    os.environ["PHOSPHOR_NOTES"] = book
    import audit
    version = open(os.path.join(ROOT, "VERSION")).read().strip()
    if not audit.seen(version, book): fails.append("release.py wouldn't find the audit of " + version)
    if audit.seen("0.0.1", book): fails.append("an audit counts for any version")
print("\n".join(fails) or "ok")
sys.exit(1 if fails else 0)
