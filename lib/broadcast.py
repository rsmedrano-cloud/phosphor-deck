"""phosphor broadcast [--host NAME]... [--role ROLE] [--timeout S] [--rolling [--pause S]] [--yes] -- COMMAND
- one command on every machine of the fleet at once.

    phosphor broadcast -- uptime
    phosphor broadcast --role storage -- df -h /srv
    phosphor broadcast --host nimbus --host relay -- 'systemctl is-active nginx'

Runs COMMAND over ssh (BatchMode: a key, never a password prompt) on every
host `phosphor fleet` watches -- viewers and `fleet = false` ones left out,
the brain itself run locally -- all in parallel, and prints each host's
output under its own header with its exit code and how long it took.
`--host` (repeatable) and `--role` narrow it down.

It can change anything on those machines, so it shows the command and the
hosts and asks first. Without a terminal it refuses unless `--yes` says the
run was meant to be unattended (a script, a cron). Exits 0 only if every
host answered 0.

`--rolling` goes one host at a time instead (the brain last) and stops at
the first one that doesn't answer 0, so a bad update breaks one machine,
not all of them. `--pause S` waits S seconds after each host and checks it
still answers ssh before going on (a restarted service, a reboot). On a
terminal it asks before each next host; with `--yes` it goes on by itself
while they keep answering 0.

Run with nothing at all on a terminal it asks: the hosts to tick (or a
whole role), then the command, then the same confirmation.
"""
import os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, DIM, FG, OK, RST, WARN
import deckconf
from sanitize import clean_text

USAGE = ("usage: phosphor broadcast [--host NAME]... [--role ROLE] [--timeout S]"
         " [--rolling [--pause S]] [--yes] -- COMMAND")


def targets(prof, names=(), role=None):
    """([host dict], [unknown names]): the fleet, as fleet polls it, narrowed."""
    fleet = [h for h in deckconf.hosts(prof)
             if h.get("fleet") is not False and (h.get("local") or h.get("role") != "viewer")]
    if role:
        fleet = [h for h in fleet if h.get("role") == role]
    if names:
        known = {h["name"] for h in fleet}
        return [h for h in fleet if h["name"] in names], [n for n in names if n not in known]
    return fleet, []


def run_one(h, command, timeout):
    """(name, exit code or None, output, seconds). None: it never answered
    (ssh couldn't connect, or the timeout ran out)."""
    argv = ["sh", "-c", command] if h.get("local") else \
           ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", deckconf.target(h), command]
    t = time.time()
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return h["name"], None, "no answer in %ds" % timeout, time.time() - t
    except OSError as e:
        return h["name"], None, str(e), time.time() - t
    out = clean_text(r.stdout + r.stderr).rstrip("\n")
    # ssh's own 255 is the link, not the command: say it didn't get there
    rc = None if (r.returncode == 255 and not h.get("local")) else r.returncode
    return h["name"], rc, out, time.time() - t


def show(result):
    name, rc, out, secs = result
    mark = OK if rc == 0 else BAD
    what = "unreachable" if rc is None else "exit %d" % rc
    print(" " + mark + " " + FG + name + RST + DIM + "  %s · %.1fs" % (what, secs) + RST)
    for line in out.splitlines() or []:
        print("     " + line)


def report(results):
    for r in results:
        show(r)
    ok = sum(1 for r in results if r[1] == 0)
    print()
    print(" " + (OK if ok == len(results) else WARN) + " %d/%d hosts answered 0" % (ok, len(results)))
    return 0 if ok == len(results) else 1


def rolling(hs, command, timeout, pause, ask):
    """One host at a time, the brain last, stopping at the first that
    doesn't answer 0 (or stops answering ssh after `pause`). `ask(name)`
    says whether to go on to the next one; exits 0 only if all ran."""
    hs = [h for h in hs if not h.get("local")] + [h for h in hs if h.get("local")]
    done = []
    for i, h in enumerate(hs):
        if i and not ask(h["name"]):
            break
        r = run_one(h, command, timeout)
        show(r)
        done.append(h["name"])
        if r[1] != 0:
            break
        if pause and i < len(hs) - 1:
            print(DIM + "     waiting %ds, then checking it still answers" % pause + RST)
            time.sleep(pause)
            back = run_one(h, "true", 30)
            if back[1] != 0:
                show(back)
                break
    left = [h["name"] for h in hs if h["name"] not in done]
    print()
    if left:
        print(" " + WARN + "stopped: not run on " + ", ".join(left) + RST)
        return 1
    print(" " + OK + "%d/%d hosts answered 0, one at a time" % (len(hs), len(hs)) + RST)
    return 0


def parse(a):
    names, role, timeout, yes, roll, pause = [], None, 60, False, False, 0
    while a and a[0] != "--":
        f = a.pop(0)
        if f in ("-h", "--help"):
            return None
        if f == "--yes":
            yes = True
        elif f == "--rolling":
            roll = True
        elif f in ("--host", "--role", "--timeout", "--pause") and a:
            v = a.pop(0)
            if f == "--host":
                names.append(v)
            elif f == "--role":
                role = v
            else:
                try:
                    n = int(v)
                except ValueError:
                    return None
                if f == "--timeout":
                    timeout = n
                else:
                    pause = n
        else:
            # no `--`: the rest is the command (phosphor broadcast uptime)
            a.insert(0, f)
            break
    if a[:1] == ["--"]:
        a.pop(0)
    if not a or (pause and not roll):
        return None
    return names, role, timeout, yes, " ".join(a), roll, pause


def interactive(prof):
    """The hosts ticked, then the command, then all at once or one at a
    time -- (names, command, rolling) or None."""
    import form
    fleet = targets(prof)[0]
    if not fleet:
        print(DIM + "  no machines in the fleet to run it on." + RST)
        return None
    roles = {}
    for h in fleet:
        roles.setdefault(h.get("role") or "-", []).append(h["name"])
    names = form.ticks("phosphor broadcast -- where?",
                       [(h["name"], (h.get("role") or "") + ("  (here)" if h.get("local") else "")) for h in fleet],
                       groups=roles if len(roles) > 1 else None)
    if not names:
        form.leave(); return None
    command = form.line("phosphor broadcast -- what?",
                        "a command for %d host%s -- Enter, then it asks once more"
                        % (len(names), "" if len(names) == 1 else "s"))
    form.leave()
    if not (command or "").strip():
        return None
    roll = False
    if len(names) > 1:
        from init import yes as ask
        roll = ask("one host at a time, stopping at the first failure?", False)
    return names, command.strip(), roll


def main():
    import form
    asking = form.wanted(sys.argv[1:])
    p = None if asking else parse(sys.argv[1:])
    if not asking and p is None:
        print(USAGE); return 0 if {"-h", "--help"} & set(sys.argv[1:]) else 1
    if deckconf.example():
        print(BAD + " no profile yet: phosphor init first (broadcast never runs on the example's machines)" + RST)
        return 1
    prof, _ = deckconf.load()
    if asking:
        got = interactive(prof)
        if got is None:
            return 0
        p = (got[0], None, 60, False, got[1], got[2], 0)
    names, role, timeout, yes, command, roll, pause = p
    hs, unknown = targets(prof, names, role)
    if unknown:
        print(BAD + " not in the fleet: " + ", ".join(unknown) + RST); return 1
    if not hs:
        print(BAD + " no host matches" + RST); return 1
    print(DIM + "  command: " + RST + command)
    print(DIM + "  on:      " + RST + ", ".join(h["name"] + (" (here)" if h.get("local") else "") for h in hs))
    if roll:
        print(DIM + "  how:     " + RST + "one at a time, stopping at the first failure"
              + (", %ds and a check between hosts" % pause if pause else ""))
    if not yes:
        if not sys.stdin.isatty():
            print(BAD + " not on a terminal: --yes to run it unattended" + RST); return 1
        from init import yes as ask
        if not ask(("start with the first of %d host%s?" if roll else "run it on %d host%s?")
                   % (len(hs), "" if len(hs) == 1 else "s"), False):
            return 1
    print()
    if roll:
        if yes:
            go = lambda name: True
        else:
            from init import yes as ask
            go = lambda name: ask("next: %s?" % name, True)
        return rolling(hs, command, timeout, pause, go)
    with ThreadPoolExecutor(max_workers=min(16, len(hs))) as ex:
        results = list(ex.map(lambda h: run_one(h, command, timeout), hs))
    return report(results)


if __name__ == "__main__":
    sys.exit(main() or 0)
