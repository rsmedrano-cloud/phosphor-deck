#!/usr/bin/env python3
"""The first-attach message invites the experience, not a key list (#6).

    python3 tests/welcome-check.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

import welcome

plain = lambda l: __import__("re").sub(r"\x1b\[[0-9;]*m", "", l)
text = "\n".join(plain(l) for l in welcome.lines({"deck": {"command": "deck"}}))

check("invites typing something", "type something" in text)
check("says leave with Ctrl-q", "Ctrl-q" in text)
check("says come back with the deck's own command", "deck" in text.split("come back with", 1)[1][:20])
check("points to the DECK tab for the rest", "DECK tab" in text)
check("doesn't enumerate keys one by one (tabs/+/exit as their own lines)",
      not any(l.strip().startswith(("tabs ", "+ ", "exit ")) for l in text.splitlines()))

text2 = "\n".join(plain(l) for l in welcome.lines({"deck": {"command": "mydeck"}}))
check("uses the profile's own command word", "mydeck" in text2)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
