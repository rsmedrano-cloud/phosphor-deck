#!/usr/bin/env python3
"""The cards card-exits-check leaves out: toggles, the ones that ask, the
ones that change things. Each tap runs here for real, with a phosphor that
only writes down what it was asked to run.

    python3 tests/card-taps-check.py [CARD...]

card.tap runs in a pseudo-terminal of its own, against a throwaway HOME,
with card.PHOSPHOR pointed at a stand-in: nothing a card would change is
touched. For each card, both ways it can go:

  back     Esc at its first question (or at its y/n): it comes back, and
           nothing ran
  through  a value for each question (a file picked, a line typed), y at
           its y/n: it comes back, and ran `phosphor NAME ARGS VALUES`,
           exactly; a toggle both ways, from on and from off
"""
import json, os, pty, select, signal, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli, dash

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".config", "phosphor"))
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
open(PROFILE, "w").write('[deck]\nsession = "card-taps"\n\n[[hosts]]\nname = "probe-brain"\n'
                         'role = "brain"\nlocal = true\n')
FAKE = os.path.join(tmp, "fake-phosphor")
open(FAKE, "w").write("import json, os, sys\n"
                      "open(os.environ['TAPS_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=os.path.join(tmp, "cache"), PHOSPHOR_NOTES=os.path.join(tmp, "notes.md"),
           XDG_RUNTIME_DIR=tmp, TERM="xterm-256color", COLUMNS="100", LINES="30",
           PATH=os.pathsep.join(p for p in ("/usr/local/bin", "/usr/bin", "/bin")))   # no zellij
CODE = ("import sys; sys.path.insert(0, %r); import card; card.PHOSPHOR = %r\n"
        "r = card.tap(sys.argv[1], {'on': True, 'off': False}.get(sys.argv[2]))\n"
        "print('TAP-' + ('RAN' if r is not None else 'NONE') + '-BACK')"
        % (os.path.join(ROOT, "lib"), FAKE))
DOWN, ESC = b"\x1b[B", b"\x1b"
# what each question shows once it's waiting for a key
LINE, FILE, YN = b"then Enter", b"which ", (b"(y/N)", b"(Y/n)")


def read(fd, secs, until):
    out, end = b"", time.time() + secs
    while time.time() < end and not until(out):
        if select.select([fd], [], [], 0.05)[0]:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    return out


def run(name, raw, steps):
    """card.tap(name) with raw ("on", "off" or "-"), answering steps
    [(what it waits for, keys)]. (how it came back, the argv it ran, why not)."""
    work = tempfile.mkdtemp(dir=tmp)                  # the file picker opens here
    open(os.path.join(work, "pick.txt"), "w").write("x")
    log = os.path.join(work, "taps.log")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(work)
        os.execve(sys.executable, [sys.executable, "-c", CODE, name, raw], dict(ENV, TAPS_LOG=log))
    out, why = b"", None
    try:
        for want, keys in steps:
            got = read(fd, 8, lambda o: any(w in o for w in (want if isinstance(want, tuple) else (want,))))
            out += got
            if not any(w in got for w in (want if isinstance(want, tuple) else (want,))):
                why = "never showed %r" % (want,)
                break
            time.sleep(0.1)
            for k in keys:                            # one key at a time, as a hand would
                os.write(fd, k)
                time.sleep(0.15)
        out += read(fd, 8, lambda o: b"-BACK" in o)
    finally:
        end = time.time() + 3
        while not os.waitpid(pid, os.WNOHANG)[0]:
            if time.time() > end:
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
                break
            time.sleep(0.05)
        os.close(fd)
    how = "ran" if b"TAP-RAN-BACK" in out else "none" if b"TAP-NONE-BACK" in out else "stuck"
    ran = [json.loads(l) for l in open(log)] if os.path.exists(log) else []
    return how, [[a.replace(work, "WORK") for a in r] for r in ran], why


def cases(name):
    """(label, raw, steps, how it should come back, the argv it should run)."""
    e = cli.entries()[name]
    c = e["card"]
    asks = c.get("ask", [])
    values = [os.path.join("WORK", "pick.txt") if a.split()[-1:] == ["file"] else "v%d" % i
              for i, a in enumerate(asks)]
    answer = [(FILE, [DOWN, b"\r"]) if a.split()[-1:] == ["file"] else (LINE, [v.encode(), b"\r"])
              for a, v in zip(asks, values)]
    confirm = [(YN, [b"y"])] if c.get("confirm") else []
    if c["kind"] == "toggle":
        runs = [("from off", "off", c["on"]), ("from on", "on", c["off"])]
    else:
        runs = [("", "-", c.get("args", []))]
    out = []
    for label, raw, args in runs:
        if asks:
            out.append(("back " + label, raw, [(LINE if answer[0][0] == LINE else FILE, [ESC])], "none", None))
        elif confirm:
            out.append(("back " + label, raw, [(YN, [ESC])], "none", None))
        out.append(("through " + label, raw, answer + confirm, "ran", [name] + list(args) + values))
    return out


def check(name):
    bad = []
    for label, raw, steps, want_how, want_argv in cases(name):
        how, ran, why = run(name, raw, steps)
        where = "%s (%s)" % (name, label.strip())
        if why:
            bad.append("%s: %s" % (where, why))
        if how == "stuck":
            bad.append("%s: the tap never came back to the cards" % where)
        elif how != want_how:
            bad.append("%s: came back %s, should have %s" % (where, "having run" if how == "ran" else "with nothing run",
                                                              "run it" if want_how == "ran" else "run nothing"))
        if want_argv is None and ran:
            bad.append("%s: Esc backed out, and it ran %s anyway" % (where, ran))
        if want_argv is not None and ran != [want_argv]:
            bad.append("%s: ran %s, not %s" % (where, ran or "nothing", want_argv))
    return bad


E = cli.entries()
left_out = [n for n in dash.gallery_names()
            if E[n]["card"]["kind"] == "toggle" or E[n]["card"].get("ask")
            or (E[n].get("mutates") and n != "fleet")]    # card-exits-check's complement
names = [n for n in left_out if n in sys.argv[1:]] or left_out
with ThreadPoolExecutor(6) as ex:
    fails = [line for bad in ex.map(check, names) for line in bad]
if fails:
    print("\n".join(fails))
    sys.exit(1)
