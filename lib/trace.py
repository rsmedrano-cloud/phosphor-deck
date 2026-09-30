"""phosphor trace TOOL - verbose logging for one tool, for a while.

    phosphor trace TOOL
    phosphor trace off TOOL

Turns on trace-TOOL.log (see `phosphor logs TOOL`): the tools that check
in with dlog.tracing() (phosphor run, so far) write a line for every
loop instead of only the ones deck.log always keeps. It turns itself off
on its own after 30 minutes, so nothing verbose is ever left running by
accident. `off TOOL` stops one sooner. With no TOOL, it lists whatever is
tracing right now -- and on a terminal, offers to start one (the tools
deck.log has lines for) or stop one.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlog
from ui import FG, DIM, AMB, RST

MINUTES = 30

def listing():
    on = dlog.active_traces()
    if not on:
        print("no trace is on. phosphor trace TOOL turns one on for %d minutes." % MINUTES)
    else:
        for tool, left in on:
            print("  " + AMB + "%-10s" % tool + RST + FG + "%d min left" % left + RST)
    return on


def start(tool):
    tool = tool.upper()
    dlog.start_trace(tool, MINUTES)
    print("  tracing " + AMB + tool + RST + " for %d minutes" % MINUTES)
    print("  " + DIM + "phosphor logs " + tool.lower() + "   reads it back" + RST)
    return 0


def interactive():
    """No arguments, on a terminal: what's on, then start or stop one."""
    import edit, form
    while True:
        on = listing()
        opts = [("t", "trace a tool")] + ([("x", "stop one")] if on else [])
        k = form.choice(opts)
        if k == "t":
            active = {t for t, _ in on}
            items = [(t, "on" if t in active else "") for t in dlog.tools_seen()]
            got = edit.pick("trace which tool, for %d minutes?" % MINUTES, items,
                            extra=[("/", "another name")])
            if got == "/":
                name = form.line("trace which tool?", "its name as deck.log writes it (FLEET, PROM...)")
                got = (name.strip(),) if name and name.strip() else None
            form.leave()
            if got:
                start(got[0])
        elif k == "x":
            got = edit.pick("stop which trace?", [(t, "%d min left" % m) for t, m in on])
            form.leave()
            if got:
                dlog.stop_trace(got[0])
                print("  " + AMB + got[0] + RST + " stopped")
        else:
            return 0
        print()


def main():
    a = sys.argv[1:]
    if not a:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return interactive()
        listing()
        return 0
    if a[0] == "off":
        if len(a) < 2:
            print("usage: phosphor trace off TOOL"); return 1
        tool = a[1].upper()
        print(("  " + AMB + tool + RST + " stopped") if dlog.stop_trace(tool) else "  no trace of %s is on" % tool)
        return 0
    return start(a[0])

if __name__ == "__main__":
    sys.exit(main() or 0)
