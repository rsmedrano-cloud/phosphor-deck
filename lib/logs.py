"""phosphor logs [TOOL] [-f] - read the deck's own log.

    phosphor logs            deck.log: crashes, hangs, exits, restarts
    phosphor logs prom       just PROM's lines (its trace file, if one is on)
    phosphor logs -f         follow, like tail -f; Ctrl-C to stop

No note text and no host names live in here -- see dlog.py and the
manual's privacy page -- so it's safe to paste into an issue.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlog
from ui import DIM, RST

def follow(path, tool=None):
    try:
        f = open(path)
    except OSError:
        return
    f.seek(0, os.SEEK_END)
    try:
        while True:
            line = f.readline()
            if not line:
                time.sleep(1); continue
            if tool:
                parts = line.split(None, 3)
                if len(parts) < 3 or parts[2].lower() != tool.lower(): continue
            sys.stdout.write(line); sys.stdout.flush()
    except KeyboardInterrupt:
        pass

def main():
    a = sys.argv[1:]
    watch = "-f" in a
    a = [x for x in a if x != "-f"]
    tool = a[0].upper() if a else None
    if tool and os.path.exists(dlog.tracefile(tool)):
        path, lines = dlog.tracefile(tool), dlog.tail(dlog.tracefile(tool), 400)
    elif tool:
        path, lines = dlog.LOG, dlog.tail_for(tool, 200)
    else:
        path, lines = dlog.LOG, dlog.tail(dlog.LOG, 200)
    if not lines and not watch:
        print("(nothing logged" + (" for %s" % tool if tool else "") + " yet)")
        return 0
    for l in lines: print(l)
    if watch:
        if path == dlog.LOG and tool:
            print(DIM + "-- following deck.log, %s only; Ctrl-C to stop --" % tool + RST)
        else:
            print(DIM + "-- following; Ctrl-C to stop --" + RST)
        follow(path, tool if path == dlog.LOG else None)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
