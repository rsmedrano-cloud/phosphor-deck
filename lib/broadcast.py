"""phosphor broadcast [--host NAME]... [--role ROLE] [--timeout S] [--yes] -- COMMAND
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
"""
import os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, DIM, FG, OK, RST, WARN
import deckconf

USAGE = "usage: phosphor broadcast [--host NAME]... [--role ROLE] [--timeout S] [--yes] -- COMMAND"


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
    out = (r.stdout + r.stderr).rstrip("\n")
    # ssh's own 255 is the link, not the command: say it didn't get there
    rc = None if (r.returncode == 255 and not h.get("local")) else r.returncode
    return h["name"], rc, out, time.time() - t


def report(results):
    for name, rc, out, secs in results:
        mark = OK if rc == 0 else BAD
        what = "unreachable" if rc is None else "exit %d" % rc
        print(" " + mark + " " + FG + name + RST + DIM + "  %s · %.1fs" % (what, secs) + RST)
        for line in out.splitlines() or []:
            print("     " + line)
    ok = sum(1 for r in results if r[1] == 0)
    print()
    print(" " + (OK if ok == len(results) else WARN) + " %d/%d hosts answered 0" % (ok, len(results)))
    return 0 if ok == len(results) else 1


def parse(a):
    names, role, timeout, yes = [], None, 60, False
    while a and a[0] != "--":
        f = a.pop(0)
        if f in ("-h", "--help"):
            return None
        if f == "--yes":
            yes = True
        elif f in ("--host", "--role", "--timeout") and a:
            v = a.pop(0)
            if f == "--host":
                names.append(v)
            elif f == "--role":
                role = v
            else:
                try:
                    timeout = int(v)
                except ValueError:
                    return None
        else:
            # no `--`: the rest is the command (phosphor broadcast uptime)
            a.insert(0, f)
            break
    if a[:1] == ["--"]:
        a.pop(0)
    if not a:
        return None
    return names, role, timeout, yes, " ".join(a)


def main():
    p = parse(sys.argv[1:])
    if p is None:
        print(USAGE); return 1
    names, role, timeout, yes, command = p
    if deckconf.example():
        print(BAD + " no profile yet: phosphor init first (broadcast never runs on the example's machines)" + RST)
        return 1
    prof, _ = deckconf.load()
    hs, unknown = targets(prof, names, role)
    if unknown:
        print(BAD + " not in the fleet: " + ", ".join(unknown) + RST); return 1
    if not hs:
        print(BAD + " no host matches" + RST); return 1
    print(DIM + "  command: " + RST + command)
    print(DIM + "  on:      " + RST + ", ".join(h["name"] + (" (here)" if h.get("local") else "") for h in hs))
    if not yes:
        if not sys.stdin.isatty():
            print(BAD + " not on a terminal: --yes to run it unattended" + RST); return 1
        from init import yes as ask
        if not ask("run it on %d host%s?" % (len(hs), "" if len(hs) == 1 else "s"), False):
            return 1
    print()
    with ThreadPoolExecutor(max_workers=min(16, len(hs))) as ex:
        results = list(ex.map(lambda h: run_one(h, command, timeout), hs))
    return report(results)


if __name__ == "__main__":
    sys.exit(main() or 0)
