"""phosphor trace TOOL - verbose logging for one tool, for a while.

    phosphor trace TOOL
    phosphor trace off TOOL
    phosphor trace --json   what's tracing, for scripts and the deck's card

Turns on trace-TOOL.log (see `phosphor logs TOOL`): the tools that check
in with dlog.tracing() (phosphor run, so far) write a line for every
loop instead of only the ones deck.log always keeps. It turns itself off
on its own after 30 minutes, so nothing verbose is ever left running by
accident. `off TOOL` stops one sooner. With no TOOL, it lists whatever is
tracing right now -- and on a terminal, offers to start one (the tools
deck.log has lines for, or any name) or stop one, in a panel.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlog, tui
from ui import FG, DIM, AMB, PH, RST, pad, emit

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
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tool):
        print("usage: phosphor trace TOOL  (a name like FLEET: letters, digits, - and _)", file=sys.stderr)
        return 2
    tool = tool.upper()
    dlog.start_trace(tool, MINUTES)
    print("  tracing " + AMB + tool + RST + " for %d minutes" % MINUTES)
    print("  " + DIM + "phosphor logs " + tool.lower() + "   reads it back" + RST)
    return 0


class Panel(tui.ListPanel):
    """The tools deck.log has lines for, and whatever is tracing: Enter
    starts one for MINUTES or stops it, / names one deck.log hasn't seen."""
    KEYS = [("enter", "trace / stop"), ("/", "another name"), ("q", "quit")]
    TITLE = "TRACE"
    SUB = "a tool's verbose log, %d minutes" % MINUTES

    def fetch(self):
        on = dict(dlog.active_traces())
        names = list(on) + [t for t in dlog.tools_seen() if t not in on]
        if not names:
            self.problem = "deck.log has no tools yet: / names one"
        return [(t, on.get(t)) for t in names]

    def lines(self, w, sel):
        out = []
        for i, (tool, left) in enumerate(self.rows):
            state = "%d min left" % left if left is not None else ""
            if i == sel:
                out.append(" " + tui.INV + pad(" %-12s %s" % (tool, state), w - 2)[:w - 2] + RST)
            else:
                out.append("  " + (AMB if left is not None else FG) + "%-12s" % tool + RST + " " + DIM + state + RST)
        return out

    def key(self, k):
        if k == "/" and not self.ask:      # works with no rows too
            name = self.line("trace which tool?")
            if name and name.strip():
                self.toggle(name.strip().upper(), None)
            return True
        return super().key(k)

    def act(self, k, row):
        self.toggle(*row)

    def toggle(self, tool, left):
        if left is None:
            dlog.start_trace(tool, MINUTES)
            self.say("tracing %s for %d minutes · phosphor logs %s reads it back" % (tool, MINUTES, tool.lower()), PH)
        else:
            dlog.stop_trace(tool)
            self.say("%s stopped" % tool)
        self.refresh()


def interactive():
    """No arguments, on a terminal: what's on, then start or stop one."""
    return Panel().run()


def main():
    a = sys.argv[1:]
    if a == ["--json"]:
        return emit({"traces": [{"tool": t, "minutes_left": left} for t, left in dlog.active_traces()],
                     "minutes": MINUTES})
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
