#!/usr/bin/env python3
"""phosphor help TOOL: a manual page's markdown image becomes a caption,
never the raw ![]() syntax -- there's no way to show an image in a terminal.

    python3 tests/docs-render-check.py
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

import docs

md = ("# Title\n\nSome text.\n\n"
      "![The COMMS tab's unread count](../img/comms-unread.png)\n\n"
      "More text with `code` and **bold**.\n")
out = re.sub(r"\x1b\[[0-9;]*m", "", docs.render(md, 80))

check("the alt text shows up", "The COMMS tab's unread count" in out)
check("never the raw markdown syntax", "![" not in out and "](.." not in out)
check("the rest of the page still renders", "Some text." in out and "code" in out and "bold" in out)

# every doc/manual page's own images render the same way, and the alt
# text is never empty (screen readers, and this caption, both need it)
MAN = os.path.join(ROOT, "doc/manual")
for name in sorted(f for f in os.listdir(MAN) if f.endswith(".md") and f != "README.md"):
    text = open(os.path.join(MAN, name)).read()
    for m in re.finditer(r"^!\[(.*?)\]\((.*?)\)$", text, re.M):
        check("%s: an image has real alt text" % name, bool(m.group(1).strip()))
        rendered = re.sub(r"\x1b\[[0-9;]*m", "", docs.render(m.group(0), 80))
        check("%s: renders as a caption, not raw markdown" % name,
              m.group(1) in rendered and "![" not in rendered)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
