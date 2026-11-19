#!/usr/bin/env python3
"""What tests/check.sh skips here, CI runs for real somewhere.

A test whose live half needs zellij (tests/zjprobe.py, "no zellij here")
prints "skipped" and passes in the check job, whose image has none: it
must be listed in the zellij job of .gitlab-ci.yml, which fetches zellij.
dash-check and zoom-check went months that way (#94). The git half is
tests/check.sh's own: under CI, no git fails instead of skipping.

    python3 tests/ci-coverage-check.py
"""
import glob, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ci = open(os.path.join(ROOT, ".gitlab-ci.yml")).read()

def job(name):
    m = re.search(r"^%s:\n(.*?)(?=^\S)" % re.escape(name), ci + "\nend:\n", re.M | re.S)
    return m.group(1) if m else ""

zellij_job = set(re.findall(r"tests/([\w-]+\.py)", job("zellij")))
check_job = job("check")
fails = []
for f in sorted(glob.glob(os.path.join(ROOT, "tests", "*-check.py"))):
    src, name = open(f).read(), os.path.basename(f)
    if name == "ci-coverage-check.py":
        continue
    live = re.search(r'zjprobe\.zellij\(\)|print\("no zellij here[^"]*skipped', src)
    if live and name not in zellij_job:
        fails.append("%s skips its zellij part without zellij, and the zellij job doesn't run it" % name)
if "sh tests/check.sh" not in check_job:
    fails.append("the check job doesn't run tests/check.sh")
if not re.search(r"\bgit\b", check_job):
    fails.append("the check job's image gets no git: the git halves of the checks would skip")
if fails:
    print("FAIL\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok: %d tests with a zellij part, all in the zellij job; the check job has git" % len(zellij_job))
