#!/usr/bin/env python3
"""Open issues (and pull requests) on the public GitHub mirror: nothing
polls these on its own, so without this they're silently ignored --
GitLab is where real dev happens and has its own tooling (mrs-check.py),
but bug reports and feature requests only ever land on GitHub.

    python3 tests/github-check.py

Always exits 0 (informational, never a blocker) -- meant to be looked at,
not gated on. Needs `gh`, logged in.
"""
import json, subprocess, sys

REPO = "rsmedrano-cloud/phosphor-deck"

def gh(*args):
    r = subprocess.run(["gh"] + list(args) + ["-R", REPO], capture_output=True, text=True)
    if r.returncode != 0:
        print("gh " + " ".join(args) + " failed: " + r.stderr.strip())
        return None
    return r.stdout

def main():
    out = gh("issue", "list", "--json", "number,title,author,createdAt,url")
    if out is None:
        return 0
    issues = json.loads(out or "[]")
    if not issues:
        print("no open issues on " + REPO)
    else:
        print("%d open issue(s) on %s:" % (len(issues), REPO))
        for i in issues:
            print("  #%d  %s  (@%s, %s)" % (i["number"], i["title"], i["author"]["login"], i["createdAt"][:10]))
            print("      " + i["url"])

    out = gh("pr", "list", "--json", "number,title,author,createdAt,url")
    prs = json.loads(out or "[]") if out is not None else []
    if prs:
        print("\n%d open pull request(s) -- main here is a squashed, force-pushed mirror, so these"
              " can't be merged as-is: point the author at an issue or a diff instead, if it's worth acting on." % len(prs))
        for p in prs:
            print("  #%d  %s  (@%s, %s)" % (p["number"], p["title"], p["author"]["login"], p["createdAt"][:10]))
            print("      " + p["url"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
