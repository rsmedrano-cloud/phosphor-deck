#!/usr/bin/env python3
"""The pictures in the docs exist, say what they show, and aren't left over.

    python3 tests/images-check.py

- every image the README or a manual page shows is there, with words for
  it (the alt text: a screen reader, a broken link, a text browser);
- every screenshot under doc/img is shown somewhere (doc/img/logo is the
  site's and GitHub's), so one that's been dropped is gone, not stale;
- every screenshot is in doc/img/shots.json with the code that draws it.

Then, without failing (a change to the code doesn't always change the
picture, and only a person can tell): the screenshots whose code changed
after they were taken, by git's dates. Those may show something that
changed or went; take them again with phosphor demo.
"""
import glob, json, os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "doc", "img")
bad = []

docs = [os.path.join(ROOT, "README.md")] + sorted(glob.glob(os.path.join(ROOT, "doc", "manual", "*.md")))
shown = set()
for d in docs:
    text = open(d).read()
    for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)", text) + \
            [("html", s) for s in re.findall(r'<img src="([^"]+)"', text)]:
        if src.startswith("http"):
            continue
        path = os.path.normpath(os.path.join(os.path.dirname(d), src))
        rel = os.path.relpath(d, ROOT)
        if not os.path.isfile(path):
            bad.append("%s shows %s, which isn't there" % (rel, src))
        if not alt.strip():
            bad.append("%s shows %s with no words for it (alt text)" % (rel, src))
        shown.add(os.path.relpath(path, IMG))

shots = json.load(open(os.path.join(IMG, "shots.json")))
on_disk = {os.path.relpath(p, IMG) for p in glob.glob(os.path.join(IMG, "**", "*.*"), recursive=True)
           if not p.endswith("shots.json")}
for p in sorted(on_disk):
    if p.startswith("logo/"):
        continue
    if p not in shown:
        bad.append("doc/img/%s isn't shown anywhere: drop it (git rm), a picture nobody sees goes stale" % p)
    if p not in shots:
        bad.append("doc/img/%s isn't in doc/img/shots.json: say which code draws what it shows" % p)
for p, s in shots.items():
    if p.startswith("_"):
        continue
    if p not in on_disk:
        bad.append("doc/img/shots.json names %s, which isn't there" % p)
    for src in s.get("shows", []):
        if not os.path.exists(os.path.join(ROOT, src)):
            bad.append("doc/img/shots.json: %s shows %s, which isn't there" % (p, src))

if bad:
    print("images-check FAILED:\n  " + "\n  ".join(bad)); sys.exit(1)

def when(*paths):
    """When git last touched paths; None without git (CI's image has none)."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%ct", "--"] + list(paths),
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        return None
    return int(out) if out.isdigit() else None

stale = []
for p, s in sorted(shots.items()):
    if p.startswith("_"):
        continue
    taken, code = when(os.path.join("doc", "img", p)), when(*s.get("shows", []))
    if taken and code and code > taken:
        stale.append(p)
print("images-check ok (%d screenshots, every one shown and described)" % len(shown - {"logo/logo-512.png"}))
if stale:
    print("  heads-up, their code changed since they were taken: " + " ".join(stale))
