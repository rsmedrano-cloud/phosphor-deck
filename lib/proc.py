"""Running other programs, one way for every module: zellij by its real
path, a command that never raises, an ssh that never asks for anything.

    proc.zellij()                    # zellij's path, or None
    proc.run(argv, timeout=20)       # CompletedProcess, text, output captured
    proc.sh("uname -m")              # (exit code, stdout stripped)
    proc.clients("deck")             # the screens attached, or None: no answer
    proc.listing("deck", "list-tabs", "-j")   # checked JSON listing, [] if no answer
    proc.layout("deck")              # dump-layout, "" if no answer
    proc.ssh("db-box", "sh -s")      # the argv of a BatchMode ssh
"""
import os, subprocess
import deckconf


def zellij():
    """zellij's path, or None: ~/.local/bin first (the zellij server's
    PATH, and a systemd unit's, lack it)."""
    return deckconf.exe("zellij")


def run(cmd, timeout=None, **kw):
    """subprocess.run with text output captured, that never raises: a
    program that's missing or runs out of time comes back as exit code -1,
    the reason in stderr. A string runs through sh."""
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                              text=True, timeout=timeout, **kw)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(cmd, -1, "", str(e))


def clients(sess=None, wait=5.0):
    """The screens attached to a zellij session, one list-clients line
    each (`sess` None: the session this runs in). Nobody attached is the
    header alone, a real answer believed at once; under load zellij can
    answer nothing at all, exit 0 (#122): asked again for `wait` seconds,
    then None (no answer, not "nobody")."""
    import time
    zj = zellij()
    if not zj:
        return None
    end = time.time() + wait
    while True:
        r = run([zj] + (["--session", sess] if sess else []) + ["action", "list-clients"], timeout=8)
        lines = (r.stdout or "").splitlines()
        if r.returncode == 0 and lines and lines[0].startswith("CLIENT_ID"):
            return [l for l in lines[1:] if l.strip()]
        if time.time() >= end:
            return None
        time.sleep(0.3)


LISTED = {"list-tabs": "position", "list-panes": "is_plugin"}   # a key every item of that list has


def action(sess, args, timeout=15):
    """One zellij action on `sess` (None: this session), a CompletedProcess
    that never raises. listing() and layout() ask through it (a test fakes it)."""
    zj = zellij()
    if not zj:
        return subprocess.CompletedProcess(args, 1, "", "no zellij")
    return run([zj] + (["--session", sess] if sess else []) + ["action"] + list(args), timeout=timeout)


def listing(sess, what, *flags, wait=5.0):
    """A zellij list action's JSON (`flags` include -j), [] when there's no
    answer (`sess` None: the session this runs in). A live session always
    has tabs and panes, so an empty or unreadable answer is zellij busy;
    and with two `zellij action`s at once, zellij 0.45 now and then hands
    one the other's answer (#122: list-panes got the tabs), so every item
    must carry its list's key. Those are asked again for `wait` seconds; a
    zellij that fails (no such session) is believed at once. Every reader
    of a listing in lib/ goes through here (#134)."""
    import json, time
    key = LISTED[what]
    end = time.time() + wait
    while True:
        r = action(sess, (what,) + flags, 15)
        if r.returncode > 0:
            return []
        try:
            got = json.loads(r.stdout or "[]")
        except ValueError:
            got = []
        if not (isinstance(got, list) and all(isinstance(x, dict) and key in x for x in got)):
            got = []
        if got or time.time() >= end:
            return got
        time.sleep(0.3)


def layout(sess=None, wait=5.0):
    """zellij's dump-layout of the session, "" when there's no answer: the
    same retries as listing(), a real one has a `tab name=` line."""
    import time
    end = time.time() + wait
    while True:
        r = action(sess, ("dump-layout",), 20)
        if r.returncode > 0:
            return ""
        if "tab name=" in (r.stdout or ""):
            return r.stdout
        if time.time() >= end:
            return ""
        time.sleep(0.3)


def sh(cmd, t=10, err=False):
    """(exit code, output stripped): stdout, plus stderr with err=True."""
    r = run(cmd, timeout=t)
    return r.returncode, ((r.stdout or "") + ((r.stderr or "") if err else "")).strip()


def ssh(target, remote, connect_t=10, persist=None):
    """The argv of an ssh to `target` running `remote` with no one there
    to answer it: BatchMode, so a host that wants a password or a new host
    key fails instead of asking. `persist` ("60s") rides FLEET's
    ControlMaster socket, one real handshake per host instead of one per
    call."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % connect_t]
    if persist:
        ctrl = os.path.join(deckconf.cache_dir(), "ssh")
        os.makedirs(ctrl, mode=0o700, exist_ok=True)
        argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=" + persist,
                 "-o", "ControlPath=" + os.path.join(ctrl, "%C")]
    return argv + [target, remote]
