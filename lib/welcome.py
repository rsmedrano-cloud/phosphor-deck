"""The first thing anyone sees before they ever attach.

Issue #6: not a list of keys to remember, an invitation to see the one
thing that matters for itself -- type something, leave, come back, it's
still there. Everything else (tabs, the + menu, every key) lives in the
DECK tab, which updates itself; repeating it here would just go stale.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BLOOM, FG, AMB, DIM, RST

def lines(prof):
    word = ((prof or {}).get("deck") or {}).get("command", "deck")
    return [
        "",
        "  " + BLOOM + "You're about to enter the deck." + RST,
        "  " + FG + "It's a session, not a program: it keeps running after you leave." + RST,
        "",
        "   " + AMB + "try it: " + RST + FG + "type something below, leave with " + RST
            + AMB + "Ctrl-q" + RST + FG + ", come back with " + RST
            + AMB + word + RST + FG + " -- even from another screen." + RST,
        "  " + DIM + "Tabs, the + menu, every key: the DECK tab has them." + RST,
    ]

PROMPT = "\n  " + DIM + "Enter to go in " + RST
