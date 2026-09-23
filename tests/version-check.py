#!/usr/bin/env python3
"""The update check's cache must never announce an older version than the
one you're already running.

Real bug (found 2026-09-18): a clone got fast-forwarded straight from
`git merge --ff-only` (the checklist AGENTS.md gives for keeping `main`
current) instead of `phosphor update`, so version.forget() never ran. The
cache still held an older "latest" from before the ff-only merge, and
`news()` only checked `latest != current`, not `latest > current` -- so it
kept reporting "new version 0.2.14" while already on 0.2.18.

    python3 tests/version-check.py

A scratch remote + clone, no network. Needs git (CI's install job has it).
"""
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

if not shutil.which("git"):
    print("no git here: skipped"); sys.exit(0)

import version

fails = []
def need(what, ok):
    if not ok: fails.append(what)

d = tempfile.mkdtemp(prefix="version-check-")
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org", GIT_CONFIG_GLOBAL="/dev/null")
os.environ.update(env)
def git(*a, cwd=None):
    r = subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()

src, remote, work = (os.path.join(d, x) for x in ("src", "remote.git", "work"))
git("init", "-q", "-b", "main", src)
open(os.path.join(src, "VERSION"), "w").write("0.1.0\n")
git("add", "-A", cwd=src); git("commit", "-q", "-m", "0.1.0", cwd=src)
git("clone", "-q", "--bare", src, remote)
git("clone", "-q", "-b", "main", remote, work)

# point the version module at the scratch clone and a throwaway cache
version.REPO = work
version.CACHE = os.path.join(d, "update.json")

# a release lands upstream: the clone checks and correctly caches it as new
open(os.path.join(src, "VERSION"), "w").write("0.1.1\n")
git("commit", "-qam", "0.1.1", cwd=src)
git("push", "-q", remote, "main", cwd=src)
res = version.check()
need("first check sees 0.1.1 as new", res["behind"] == 1 and res["latest"] == "0.1.1")
need("news reports it", version.news() == "new version 0.1.1")

# a further release lands, and `work` is fast-forwarded straight to it --
# NOT through `phosphor update`, so the cache above is never forget()'d
open(os.path.join(src, "VERSION"), "w").write("0.1.2\n")
git("commit", "-qam", "0.1.2", cwd=src)
git("push", "-q", remote, "main", cwd=src)
git("fetch", "-q", cwd=work)
git("merge", "-q", "--ff-only", "origin/main", cwd=work)

need("work caught up to 0.1.2", open(os.path.join(work, "VERSION")).read().strip() == "0.1.2")
need("stale cache detected (commit moved underneath it)", version.stale())
need("news never announces an older version than current",
     version.news() == "")

# once a fresh check runs, it reports there's genuinely nothing newer
res = version.check()
need("fresh check: no news", version.news() == "" and res["behind"] == 0)

shutil.rmtree(d, ignore_errors=True)
if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("ok")
