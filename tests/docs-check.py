#!/usr/bin/env python3
"""The docs say what the code does.

    python3 tests/docs-check.py              what needs no git (check.sh)
    python3 tests/docs-check.py BASE HEAD    also: code changed in BASE..HEAD
                                             came with CHANGELOG.md (CI)

- every `phosphor COMMAND` in `phosphor help` is in the manual's commands
  page and in the README;
- every manual page is in the manual's index;
- a push that changes lib/, phosphor, share/ or install.sh also changes
  CHANGELOG.md, unless a commit in it says [no-changelog] (a refactor users
  never see);
- and so does everything since the last release tag: a push is judged
  against the one before it, so a red push followed by another one (a second
  merge request) would otherwise wash the missing entry out.
"""
import os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = []

usage = open(os.path.join(ROOT, "phosphor")).read().split('USAGE = """', 1)[1].split('"""', 1)[0]
commands = sorted(set(re.findall(r"^\s*phosphor ([a-z][a-z-]*)", usage, re.M)))
manual = open(os.path.join(ROOT, "doc/manual/commands.md")).read()
readme = open(os.path.join(ROOT, "README.md")).read()
for c in commands:
    if "phosphor " + c not in manual:
        bad.append("doc/manual/commands.md doesn't mention `phosphor %s`" % c)
    if "phosphor " + c not in readme and "/ `%s`" % c not in readme:     # "`phosphor up` / `down`"
        bad.append("README.md doesn't mention `phosphor %s`" % c)

index = open(os.path.join(ROOT, "doc/manual/README.md")).read()
for f in sorted(os.listdir(os.path.join(ROOT, "doc/manual"))):
    if f.endswith(".md") and f != "README.md" and "| %s |" % f[:-3] not in index:
        bad.append("doc/manual/README.md's index lacks %s" % f[:-3])

if len(sys.argv) == 3:
    base, head = sys.argv[1], sys.argv[2]
    git = lambda *a: subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True)
    is_code = lambda f: f == "phosphor" or f == "install.sh" or f.startswith(("lib/", "share/"))
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", head).stdout.strip()
    if tag:
        since = git("diff", "--name-only", tag, head).stdout.split()
        undocumented = []
        for sha in git("rev-list", "--no-merges", "%s..%s" % (tag, head)).stdout.split():
            msg = git("log", "-1", "--format=%B", sha).stdout
            touched = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split()
            if "[no-changelog]" not in msg and any(map(is_code, touched)):
                undocumented.append("%s %s" % (sha[:7], msg.splitlines()[0] if msg.strip() else ""))
        if undocumented and "CHANGELOG.md" not in since:
            bad.append("code changed since %s but CHANGELOG.md didn't: %s" % (tag, "; ".join(undocumented[:4])))
    else:
        print("no release tag to compare with: changelog-since-release check skipped")
    if base.strip("0") and git("cat-file", "-e", base).returncode == 0:
        files = git("diff", "--name-only", base, head).stdout.split()
        code = [f for f in files if is_code(f)]
        waived = "[no-changelog]" in git("log", "--format=%B", "%s..%s" % (base, head)).stdout
        if code and "CHANGELOG.md" not in files and not waived:
            bad.append("code changed (%s) but CHANGELOG.md didn't: say what users get under"
                       " ## Unreleased, or mark a refactor [no-changelog]" % ", ".join(code[:4]))
    else:
        print("no base to compare with (a new branch?): changelog check skipped")

if bad:
    print("\n".join(bad)); sys.exit(1)
