#!/usr/bin/env python3
"""docs/ (the GitHub Pages site, github.com/rsmedrano-cloud/phosphor-deck)
is generated from doc/manual/*.md by doc/site/build.py -- this fails when
it's stale, the same way `phosphor docs --check` catches an AGENTS.md
nobody rebuilt after editing the manual.

    python3 tests/site-check.py
"""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "doc", "site"))
import build

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

real_out = build.OUT
tmp = tempfile.mkdtemp()
build.OUT = tmp
try:
    build.main()
finally:
    build.OUT = real_out

live = os.path.join(ROOT, "docs")
check("docs/ exists (run python3 doc/site/build.py once)", os.path.isdir(live))

def files_under(root):
    out = set()
    for dirpath, _, names in os.walk(root):
        for n in names:
            out.add(os.path.relpath(os.path.join(dirpath, n), root))
    return out

if os.path.isdir(live):
    fresh, committed = files_under(tmp), files_under(live)
    for f in sorted(committed - fresh):
        fails.append("docs/%s is stale (build.py doesn't generate this anymore)" % f)
    for f in sorted(fresh - committed):
        fails.append("docs/%s is missing" % f)
    for f in sorted(fresh & committed):
        with open(os.path.join(tmp, f), "rb") as a, open(os.path.join(live, f), "rb") as b:
            if a.read() != b.read():
                fails.append("docs/%s differs from a fresh build" % f)

if fails:
    print("FAILED (run: python3 doc/site/build.py):\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
