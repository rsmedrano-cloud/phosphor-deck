"""phosphor stats - which phosphor commands get run here, counted locally.

    phosphor stats           typed most first, then what only panes and scripts
                             run, then the ones never run since counting began
    phosphor stats --json    the same, for scripts
    phosphor stats --clear   start counting again from today

Every `phosphor CMD` adds one to CMD's count in ~/.cache/phosphor/stats.json:
the command's name only (never its arguments), how it was started, and the
day it last ran. It never leaves this machine; it's there so the next
round of removals (doc/manual/api.md) is decided on data, not on a guess.

How it was started, because a tab that opens on every restart isn't the
same signal as something typed:
    terminal   typed in a shell, or a key that opens it in a pane
    pane       a tab's pane, started by phosphor run
    script     no terminal: a timer, a hook, another program
Hidden commands (phosphor run, mention-hook) are plumbing, not counted.
The panel reads terminal first: a card refreshing every few seconds runs
thousands of times, and that says nothing about what people use.
"""
import json, os, sys, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli, dlog
from ui import DIM, RST, emit

FILE = os.path.join(dlog.DIR, "stats.json")
WAYS = ("terminal", "pane", "script")


def _today():
    return time.strftime("%Y-%m-%d")


def _empty():
    return {"since": _today(), "commands": {}}


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("commands"), dict) and d.get("since"):
            return d
    except (OSError, ValueError):
        pass
    return _empty()


def _save(d):
    tmp = "%s.%d" % (FILE, os.getpid())
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, FILE)


def way():
    """terminal, pane or script: how this phosphor was started. phosphor run
    sets PHOSPHOR_RUN to "PID NAME"; a shell typed into that pane inherits
    it, but then the parent is the shell, not the run."""
    pid = os.environ.get("PHOSPHOR_RUN", "").partition(" ")[0]
    if pid and pid == str(os.getppid()):
        return "pane"
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return "terminal"
    except (ValueError, AttributeError):
        pass
    return "script"


def count(cmd):
    """One more run of cmd, if it's a command of the manifest's and not a
    hidden one. Never fails the command it counts: a full disk or a
    read-only cache just means this run isn't counted."""
    e = cli.get(cmd)
    if not e or e.get("hidden"):
        return
    name = cli.resolve(cmd)
    try:
        import fcntl
        os.makedirs(dlog.DIR, exist_ok=True)
        # several phosphors start at once on a restart: one at a time here
        with open(FILE + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = load()
            c = d["commands"].setdefault(name, {})
            w = way()
            c[w] = c.get(w, 0) + 1
            c["last"] = _today()
            _save(d)
    except (OSError, ValueError, ImportError):
        pass


def summary():
    """{since, commands: [{name, runs, terminal, pane, script, last}], never: [names]}:
    commands typed most first, then by all their runs."""
    d = load()
    rows = []
    for name, c in d["commands"].items():
        r = {"name": name, "runs": sum(c.get(w, 0) for w in WAYS)}
        r.update({w: c.get(w, 0) for w in WAYS})
        r["last"] = c.get("last", "")
        rows.append(r)
    rows.sort(key=lambda r: (-r["terminal"], -r["runs"], r["name"]))
    seen = {r["name"] for r in rows}
    never = [n for n in cli.entries() if n not in seen]
    return {"since": d["since"], "commands": rows, "never": never}


def main():
    a = sys.argv[1:]
    if "--clear" in a:
        try:
            os.remove(FILE)
        except OSError:
            pass
        print("stats cleared: counting again from %s" % _today())
        return 0
    s = summary()
    if "--json" in a:
        return emit(s)
    print("phosphor commands run here since %s (counted on this machine only)" % s["since"])
    if not s["commands"]:
        print(DIM + "  nothing counted yet" + RST)
    typed = [r for r in s["commands"] if r["terminal"]]
    rest = [r for r in s["commands"] if not r["terminal"]]
    for rows, title in ((typed, None), (rest, "run only by panes and scripts (cards, timers, hooks):")):
        if not rows:
            continue
        if title:
            print("\n" + title)
        print(DIM + "  %-14s %9s %6s %7s %6s  %s" % ("command", "terminal", "pane", "script", "runs", "last") + RST)
        for r in rows:
            print("  %-14s %9d %6d %7d %6d  %s" % (r["name"], r["terminal"], r["pane"],
                                                    r["script"], r["runs"], r["last"]))
    if s["never"]:
        print("\nnever run since %s:" % s["since"])
        print(textwrap.fill(", ".join(s["never"]), 78, initial_indent="  ", subsequent_indent="  "))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
