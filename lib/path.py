#!/usr/bin/env python3
"""Turns a path in the fleet tree (~/fleet) into host:/real/path.

The map comes from the profile, the same one gen mounts with, so what yazi
shows and what this translates can't drift apart."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

_prof, _ = deckconf.load()
ROOT = deckconf.mount_root(_prof)
MAP  = [(pre, (host, base)) for pre, host, base in deckconf.fleet_map(_prof)]

def translate(p):
    p = os.path.abspath(os.path.expanduser(p))
    if not p.startswith(ROOT): return p
    rel = os.path.relpath(p, ROOT)
    for prefix, (host, base) in MAP:
        if rel == prefix or rel.startswith(prefix + os.sep):
            tail = os.path.relpath(rel, prefix)
            real = base if tail == "." else os.path.join(base, tail)
            return "%s:%s" % (host, real)
    return p
if __name__ == "__main__":
    args = sys.argv[1:] or [os.getcwd()]
    for a in args: print(translate(a))
