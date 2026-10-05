"""The fleet's last 24 hours, without Prometheus: every 5 minutes, each
host's peak CPU, RAM, temperature and fullest disk in that window go into
history.json next to fleet.json, and `h` over a FLEET card draws them.

The deck's own fleet process records it out of fleet.json (whichever poller
wrote that, Python or Rust), so nothing new runs anywhere. A slot written
twice (two fleet panes) keeps the higher reading: the file only ever holds
peaks. A host that answered no poll in a slot is recorded as down."""
import json, os, time
import deckconf

STEP   = 300                    # seconds per slot
KEEP   = 24 * 3600 // STEP      # 288 slots: a day
SERIES = (("CPU", "%"), ("RAM", "%"), ("TEMP", "°C"), ("DISK", "%"))
TICKS  = "▁▂▃▄▅▆▇█"

def path():
    return os.path.join(deckconf.cache_dir(), "history.json")

def reading(d):
    """[cpu %, ram %, temp °C or None, fullest disk % or None] from one
    host's poll, or None when it's down. Never trusts a type: fleet.json can
    come from either poller, of any age."""
    if not d or not d.get("ok"):
        return None
    def num(v):
        try: return int(v)
        except (TypeError, ValueError): return None
    cpu = num(d.get("CPU")) or 0
    mt = num(d.get("MEMT")) or 0
    ram = int(round((num(d.get("MEMU")) or 0) * 100.0 / mt)) if mt else 0
    disks = [num(m[1]) for m in d.get("mnt") or [] if isinstance(m, (list, tuple)) and len(m) > 1]
    disks = [p for p in disks if p is not None]
    return [cpu, ram, num(d.get("TEMP")), max(disks) if disks else None]

def peak(a, b):
    """Two readings of the same slot -> the higher of each; down only when
    both were."""
    if a is None: return b
    if b is None: return a
    return [y if x is None else x if y is None else max(x, y) for x, y in zip(a, b)]

def load():
    try:
        with open(path()) as f:
            h = json.load(f).get("hosts", {})
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}

def merge(hosts, slot, readings, now_slot=None):
    """Put {host: reading} into `hosts` ({host: [[slot, reading], ...]}) at
    `slot`, keeping peaks, and drop what's older than a day."""
    oldest = (now_slot if now_slot is not None else slot) - KEEP + 1
    for n, r in readings.items():
        rows = hosts.setdefault(n, [])
        if rows and rows[-1][0] == slot:
            rows[-1][1] = peak(rows[-1][1], r)
        else:
            rows.append([slot, r])
            rows.sort(key=lambda x: x[0])
    for n in list(hosts):
        hosts[n] = [x for x in hosts[n] if x[0] >= oldest]
        if not hosts[n]:
            del hosts[n]
    return hosts

def save(hosts):
    try:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        tmp = path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"step": STEP, "hosts": hosts}, f, separators=(",", ":"))
        os.replace(tmp, path())
    except OSError as e:
        import dlog
        dlog.event_throttled("FLEET", "history-write-failed", str(e)[:60])

class Recorder:
    """Fed fleet.json's hosts every frame; writes a slot once it's over."""
    def __init__(self):
        self.slot, self.acc, self.seen = None, {}, 0

    def feed(self, state, t, now=None):
        """`state`: fleet.json's hosts; `t`: when it was written. A stale
        file (the poller died) records nothing rather than a frozen past."""
        now = now if now is not None else time.time()
        slot = int(now // STEP)
        if self.slot is not None and slot != self.slot:
            self.flush(now)
        self.slot = slot
        if now - (t or 0) > 90 or t == self.seen:
            return
        self.seen = t
        for n, d in state.items():
            r = reading(d)
            self.acc[n] = peak(self.acc[n], r) if n in self.acc else r

    def flush(self, now=None):
        if self.slot is None or not self.acc:
            return
        now = now if now is not None else time.time()
        save(merge(load(), self.slot, self.acc, int(now // STEP)))
        self.acc = {}

def columns(rows, now_slot, width):
    """A host's rows -> `width` columns covering the day up to now_slot, each
    the peak of the slots it covers: a reading, None (down) or "" (no data)."""
    first = now_slot - KEEP + 1
    by = {s: r for s, r in rows}
    out = []
    for c in range(width):
        a = first + c * KEEP // width
        b = first + (c + 1) * KEEP // width
        got, any_ = None, False
        for s in range(a, max(b, a + 1)):
            if s in by:
                any_ = True
                got = peak(got, by[s])
        out.append(got if any_ else "")
    return out

def spark(cols, i, top):
    """One series (index i) as a line of ticks, scaled to `top`; a down
    column is "·", no data is a space. Returns [(char, value)]."""
    out = []
    for c in cols:
        if c == "":
            out.append((" ", None))
        elif c is None:
            out.append(("·", None))
        elif c[i] is None:
            out.append((" ", None))
        else:
            v = c[i]
            out.append((TICKS[min(len(TICKS) - 1, max(0, int(v * len(TICKS) / max(1, top))))], v))
    return out

def summary(rows, i, now_slot):
    """(peak, when it was, latest) of series i over the day, or None."""
    best, when, last = None, None, None
    for s, r in rows:
        if s < now_slot - KEEP + 1 or not r or r[i] is None:
            continue
        if best is None or r[i] >= best:
            best, when = r[i], s
        last = r[i]
    return None if best is None else (best, when, last)

def downtime(rows, now_slot):
    """Minutes the host spent down in the last day, as far as recorded."""
    return sum(STEP // 60 for s, r in rows if r is None and s >= now_slot - KEEP + 1)

def seed_demo(names, base, now=None):
    """A believable day for `phosphor demo`, so `h` has something to show on
    the first run: the base readings with a daily rhythm, one host running
    hot overnight and one short outage."""
    import math, random
    now = now if now is not None else time.time()
    ns = int(now // STEP)
    rnd = random.Random(7)
    hosts = {}
    for k, n in enumerate(names):
        b = base.get(n) or {}
        rows = []
        for s in range(ns - KEEP + 1, ns):
            day = math.sin((s % KEEP) / KEEP * 2 * math.pi + k)
            cpu = b.get("cpu", 20) * (1 + 0.5 * day) + rnd.uniform(-4, 4)
            if n == "forge" and KEEP // 3 < ns - s < KEEP // 3 + 18:
                cpu = 96 + rnd.uniform(-3, 3)           # the overnight build
            temp = b.get("temp")
            if temp:
                temp = int(temp + (cpu - b.get("cpu", 20)) * 0.3 + rnd.uniform(-1, 1))
            mnt = [p for _, p, _ in b.get("mnt", [])]
            r = [int(max(1, min(100, cpu))),
                 int(max(1, min(99, b.get("mem", 0.3) * 100 + 6 * day + rnd.uniform(-2, 2)))),
                 temp, max(mnt) if mnt else None]
            if n == "relay" and 40 < ns - s < 47:
                r = None                                # its short outage
            rows.append([s, r])
        hosts[n] = rows
    save(hosts)

def view(name, rows, cols, lines, now=None):
    """The history screen for one host: a sparkline per series across the
    day, its peak (and when) and its latest reading. At most `lines` lines,
    none wider than `cols`."""
    from ui import FG, DIM, MUTE, BLOOM, PH, AMB, RED, RULE, RST, vcut
    now = now if now is not None else time.time()
    ns = int(now // STEP)
    w = max(12, min(KEEP, cols - 14))
    cols_ = columns(rows, ns, w)
    out = [BLOOM + " " + name.upper() + RST + DIM + "  · the last 24 hours, peak of every "
           + str(STEP // 60) + " minutes" + RST, ""]
    if not rows:
        out += [FG + " nothing recorded yet" + RST,
                DIM + " a reading goes in every %d minutes while the deck runs" % (STEP // 60) + RST]
    def tone(label, v):
        if v is None: return DIM
        if label == "TEMP": return PH if v < 70 else AMB if v < 85 else RED
        return PH if v < 60 else AMB if v < 85 else RED
    for i, (label, unit) in enumerate(SERIES):
        s = summary(rows, i, ns)
        if s is None:
            continue
        best, when, last = s
        top = 100 if unit == "%" else max(90, best)
        line = MUTE + " %-5s" % label + RST + RULE + "│" + RST
        for ch, v in spark(cols_, i, top):
            line += (RED + ch + RST) if ch == "·" else (tone(label, v) + ch + RST)
        out.append(vcut(line, cols))
        out.append(vcut(DIM + "       peak " + RST + tone(label, best) + "%d%s" % (best, unit) + RST
                        + DIM + " at " + time.strftime("%H:%M", time.localtime(when * STEP))
                        + "  · now " + RST + FG + "%d%s" % (last, unit) + RST, cols))
        out.append("")
    if rows:
        axis = ("-24h".ljust(w // 2 - 2) + "-12h").ljust(w - 3) + "now"
        out.append(DIM + "       " + axis[:w] + RST)
        down = downtime(rows, ns)
        if down:
            out.append(RED + " · " + RST + DIM + "down about %d min in the day" % down + RST)
    return [vcut(o, cols) for o in out[:max(1, lines)]]
