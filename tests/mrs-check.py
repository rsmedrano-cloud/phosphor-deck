#!/usr/bin/env python3
"""Open merge requests: does dev already have them cleanly, and do the
fast checks still pass once they're in.

    python3 tests/mrs-check.py [TARGET...]

.gitlab-ci.yml only runs the pipeline on protected refs (main, dev, tags):
a merge request's own branch is never run automatically, on purpose, so
nobody's code runs on the runner before it's looked at. This is the
stand-in for that pipeline, meant to run before merging one or cutting a
release: a real merge into a throwaway git worktree (nothing is pushed,
nothing on GitLab moves) and `sh tests/check.sh` against the result.
TARGET narrows to merge requests into those branches (default: dev main).
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def remote():
    remotes = subprocess.run(["git", "remote"], capture_output=True, text=True).stdout.split()
    return "gitlab" if "gitlab" in remotes else "origin"

def open_mrs():
    r = subprocess.run(["glab", "mr", "list", "--output", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        print("glab mr list failed: " + r.stderr.strip()); return []
    return json.loads(r.stdout or "[]")

def check_one(rem, mr):
    iid, src, base = mr["iid"], mr["source_branch"], mr["target_branch"]
    print("\n!%d  %s -> %s  (%s)" % (iid, src, base, mr["author"]["username"]))
    print("    " + mr["title"])
    if mr.get("draft"):
        print("    draft: not asking to be merged yet")
    if mr.get("has_conflicts"):
        print("    CONFLICTS with " + base + " (GitLab already flags this one)")
        return False
    subprocess.run(["git", "fetch", "-q", rem, src, base], capture_output=True)
    tmp = tempfile.mkdtemp(prefix="phosphor-mr%d-" % iid)
    added = subprocess.run(["git", "worktree", "add", "--detach", "-q", tmp, "%s/%s" % (rem, base)],
                            capture_output=True, text=True)
    if added.returncode != 0:
        print("    couldn't check it out: " + added.stderr.strip()); return False
    try:
        m = subprocess.run(["git", "-C", tmp, "merge", "--no-edit", "-q", "%s/%s" % (rem, src)],
                            capture_output=True, text=True)
        if m.returncode != 0:
            print("    CONFLICTS merging into a throwaway copy of " + base + ":")
            for l in (m.stdout + m.stderr).splitlines():
                if l.strip(): print("      " + l.strip())
            subprocess.run(["git", "-C", tmp, "merge", "--abort"], capture_output=True)
            return False
        c = subprocess.run(["sh", "tests/check.sh"], cwd=tmp, capture_output=True, text=True)
        if c.returncode != 0:
            print("    merges cleanly, but sh tests/check.sh fails once it's in:")
            for l in c.stdout.splitlines():
                if "FAIL" in l: print("      " + l.strip())
            return False
        print("    merges cleanly, and the fast checks still pass")
        return True
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], capture_output=True)

def main():
    targets = sys.argv[1:] or ["dev", "main"]
    rem = remote()
    mrs = [m for m in open_mrs() if m["target_branch"] in targets]
    if not mrs:
        print("no open merge requests into " + " or ".join(targets)); return 0
    bad = [m for m in mrs if not check_one(rem, m)]
    print("\n%d open, %d need a look before merging" % (len(mrs), len(bad)))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
