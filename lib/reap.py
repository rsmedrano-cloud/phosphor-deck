"""Which processes belong to a deck session.

`phosphor restart` has to stop the panes of one session: killing the zellij
server doesn't (KillMode=process keeps them alive on purpose, and they
outlive it). Matching them by what they run was too wide — every process
with "phosphor" in its command line matched, CI jobs and editors included.

zellij exports ZELLIJ_SESSION_NAME into every pane, and a process keeps the
environment it was started with, so that is the mark. The session's own
server and any client attached to it are named in their command line.
"""
import os, re

def env_of(pid):
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            return f.read().split(b"\0")
    except OSError:
        return []

def is_client(args):
    """A screen's launcher waits out the restart and goes back in: spare it."""
    return bool(re.search(r"phosphor (attach|deck)\s*$", args))

def targets(procs, session, protect=(), environ=env_of):
    """[(pid, args)] to stop: the session's panes, its server, its clients.

    procs is [(pid, args)]; protect holds pids that must survive (this
    process and its parents); environ reads a pid's environment.
    """
    mark = ("ZELLIJ_SESSION_NAME=%s" % session).encode()
    server = re.compile(r"zellij --server .*/%s(\s|$)" % re.escape(session))
    client = re.compile(r"zellij attach (--\S+ )*%s(\s|$)" % re.escape(session))
    out = []
    for pid, args in procs:
        if pid in protect or is_client(args):
            continue
        if server.search(args) or client.search(args) or mark in environ(pid):
            out.append((pid, args))
    return out


BUSY = ("active", "activating", "deactivating", "reloading", "refreshing")

def down_problems(gone, service, left, session="deck"):
    """What still stands between `phosphor down` and a clean slate: [] means
    the old deck is gone and a new one may start. `gone` is whether zellij
    no longer lists the session (a dead entry would be resurrected with the
    old layout), `service` what `systemctl is-active` says about its unit,
    `left` the reap targets that outlived SIGKILL."""
    out = []
    if not gone:
        out.append("zellij still lists the session '%s'" % session)
    if service in BUSY:
        out.append("%s.service is still %s" % (session, service))
    for pid, args in left:
        out.append("pid %d still running: %s" % (pid, args[:70]))
    return out
