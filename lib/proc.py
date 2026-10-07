"""Running other programs, one way for every module: zellij by its real
path, a command that never raises, an ssh that never asks for anything.

    proc.zellij()                    # zellij's path, or None
    proc.run(argv, timeout=20)       # CompletedProcess, text, output captured
    proc.sh("uname -m")              # (exit code, stdout stripped)
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
