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
