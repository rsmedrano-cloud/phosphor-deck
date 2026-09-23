"""phosphor trace TOOL - verbose logging for one tool, for a while.

    phosphor trace TOOL

Turns on trace-TOOL.log (see `phosphor logs TOOL`): the tools that check
in with dlog.tracing() (phosphor run, so far) write a line for every
loop instead of only the ones deck.log always keeps. It turns itself off
on its own after 30 minutes, so nothing verbose is ever left running by
accident. With no TOOL, it lists whatever is tracing right now.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlog
from ui import FG, DIM, AMB, RST

MINUTES = 30

def main():
    a = sys.argv[1:]
    if not a:
        on = dlog.active_traces()
        if not on:
            print("no trace is on. phosphor trace TOOL turns one on for %d minutes." % MINUTES)
        else:
            for tool, left in on:
                print("  " + AMB + "%-10s" % tool + RST + FG + "%d min left" % left + RST)
        return 0
    tool = a[0].upper()
    dlog.start_trace(tool, MINUTES)
    print("  tracing " + AMB + tool + RST + " for %d minutes" % MINUTES)
    print("  " + DIM + "phosphor logs " + tool.lower() + "   reads it back" + RST)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
