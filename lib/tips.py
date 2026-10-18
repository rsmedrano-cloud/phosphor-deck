"""Did you know: one thing the deck can do, a different one every while.

The deck does more than anyone keeps in their head, so the DECK tab's
second line, when nothing more urgent wants it, says one of them: what a
command does (its summary in share/commands.json) and where it is (its
key in the DECK tab, a key of the deck, else the command). Nothing is
written by hand, so a tip is never stale: a new command is a new tip.

The ones you've never run here come first (`phosphor stats` counts them,
on this machine only); once you've tried everything, it goes round all
of them. A new one every EVERY seconds, the same on every screen.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli

EVERY = 600


def where(cmd, keys):
    """How to reach cmd from the deck: keys is {command: DECK key}."""
    if cmd == "note":                     # N in DECK too, but this one works anywhere
        return "Alt-j in any tab"
    if cmd in keys:
        return keys[cmd] + " in the DECK tab"
    return "phosphor " + cmd


def all_tips(keys):
    """[(command, tip)] for every public command with a card worth a tap:
    plumbing is how other things work, not something to remember."""
    out = []
    for name, e in sorted(cli.entries().items()):
        c = e.get("card") or {}
        if e.get("hidden") or c.get("kind") in (None, "plumbing") or not e.get("summary"):
            continue
        out.append((name, e["summary"] + " · " + where(name, keys)))
    return out


def pick(keys, now=None, used=None):
    """(command, tip) for now: the never-run ones first, in turns."""
    tips = all_tips(keys)
    if not tips:
        return None
    if used is None:
        try:
            import stats
            # by hand only: the cards' own --json reads count as "script"
            used = {c for c, v in stats.load()["commands"].items() if v.get("terminal") or v.get("pane")}
        except Exception:
            used = set()
    fresh = [t for t in tips if t[0] not in used] or tips
    slot = int((time.time() if now is None else now) // EVERY)
    return fresh[slot % len(fresh)]
