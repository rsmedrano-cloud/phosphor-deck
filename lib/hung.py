"""Tell a program that froze from one that is just quiet.

A TUI that deadlocks keeps its last frame on screen: the pane looks alive
and says nothing (btop once sat on "Terminal size too small" for an hour
while the pane was 125x37). The sign that works for any program: the
terminal changed size, the kernel queued SIGWINCH, and the program neither
took it nor used any CPU for a while. A healthy one answers a resize in
milliseconds; one that ignores SIGWINCH never gets it queued at all.
"""
import os

WINCH = 1 << 27          # SIGWINCH (28) in /proc's signal masks

def mask(status, key):
    for line in status.splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1], 16)
    return 0

def waiting(status):
    """A resize queued and blocked, in this task's status text."""
    pend = mask(status, "SigPnd") | mask(status, "ShdPnd")
    return bool(pend & WINCH) and bool(mask(status, "SigBlk") & WINCH)

def read(path):
    try:
        with open(path) as f: return f.read()
    except OSError:
        return None

def tree(root):
    """root and every process below it. One pass over /proc (a few ms)."""
    kids = {}
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        st = read("/proc/%s/stat" % d)
        if st:
            kids.setdefault(int(st.rsplit(")", 1)[1].split()[1]), []).append(int(d))
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out

def stuck(pids, tty):
    """{pid: cpu ticks} of these processes, on this terminal, that have a
    resize waiting in every thread."""
    found = {}
    for pid in pids:
        st = read("/proc/%d/stat" % pid)
        if not st: continue
        f = st.rsplit(")", 1)[1].split()
        if int(f[4]) != tty or f[0] in "TtZX": continue    # elsewhere, Ctrl-Z'd, finished
        try:
            tasks = os.listdir("/proc/%d/task" % pid)
        except OSError:
            continue
        texts = [read("/proc/%d/task/%s/status" % (pid, t)) for t in tasks]
        if texts and all(t and waiting(t) for t in texts):
            found[pid] = int(f[11]) + int(f[12])
    return found

class Watch:
    """Call tick() every few seconds; it returns the pid that has been stuck,
    with no CPU spent, for `after` seconds, else None. The pane's processes
    are listed again every `rescan` seconds; a tick in between reads only
    their own status."""
    def __init__(self, root, tty, after=20.0, rescan=30.0):
        self.root, self.tty, self.after, self.rescan = root, tty, after, rescan
        self.seen, self.pids, self.listed = {}, [], None

    def tick(self, now):
        if self.listed is None or now - self.listed >= self.rescan:
            self.pids, self.listed = tree(self.root), now
        cur = stuck(self.pids, self.tty)
        self.seen = {p: v for p, v in self.seen.items() if p in cur and cur[p] == v[1]}
        for p, cpu in cur.items():
            self.seen.setdefault(p, (now, cpu))
        for p, (since, _) in self.seen.items():
            if now - since >= self.after:
                return p
        return None
