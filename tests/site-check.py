#!/usr/bin/env python3
"""site/ (the Astro + Starlight docs site, published to
rsmedrano-cloud.github.io/phosphor-deck by .github/workflows/pages.yml) has
its content and images generated from doc/manual/*.md and doc/img by
doc/site/build.py -- this fails when they're stale, the same way `phosphor
docs --check` catches an AGENTS.md nobody rebuilt after editing the manual.

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

real_site = build.SITE
tmp = tempfile.mkdtemp()
build.SITE = tmp
try:
    build.main()
finally:
    build.SITE = real_site

def files_under(root):
    out = set()
    for dirpath, _, names in os.walk(root):
        for n in names:
            out.add(os.path.relpath(os.path.join(dirpath, n), root))
    return out

def compare(label, fresh_root, live_root):
    check("%s exists (run python3 doc/site/build.py once)" % label, os.path.isdir(live_root))
    if not os.path.isdir(live_root):
        return
    fresh, committed = files_under(fresh_root), files_under(live_root)
    for f in sorted(committed - fresh):
        fails.append("%s/%s is stale (build.py doesn't generate this anymore)" % (label, f))
    for f in sorted(fresh - committed):
        fails.append("%s/%s is missing" % (label, f))
    for f in sorted(fresh & committed):
        with open(os.path.join(fresh_root, f), "rb") as a, open(os.path.join(live_root, f), "rb") as b:
            if a.read() != b.read():
                fails.append("%s/%s differs from a fresh build" % (label, f))

compare("site/src/content/docs", os.path.join(tmp, "src", "content", "docs"),
        os.path.join(real_site, "src", "content", "docs"))
compare("site/src/assets", os.path.join(tmp, "src", "assets"),
        os.path.join(real_site, "src", "assets"))

if fails:
    print("FAILED (run: python3 doc/site/build.py):\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
