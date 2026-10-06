#!/usr/bin/env python3
"""phosphor fleet - one card per machine: CPU, RAM, load, GPU, disks and
containers, collected by piping share/collect.sh over ssh (no agents).

Runs as the deck's always-on background worker (poller, unfreezer, the
mentions marker) even when nobody has this tab open. It's also where a
host's ok/not-ok flipping calls `phosphor notify` itself: down, or back,
at most once a minute per host so a flapping link doesn't flood.

The poller itself is optional here: `start_poller()` hands the job to
`rust/fleet-poll` (its own binary, its own README) when one is installed,
since it only ever talks to this file's own reader through fleet.json --
falls back to the thread below otherwise, so nothing changes for a
checkout without a Rust toolchain."""
import json, math, os, random, shutil, signal, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf
from health import sensors, updates, LOW_BAT
from sanitize import clean, clean_tree

HOME     = os.path.expanduser("~")
COLLECT  = share("collect.sh")
HOSTS    = []   # [(name, ssh target | None = this machine)], from the profile in main()
INTERVAL = 15
DEMO     = False
CACHE    = os.path.join(deckconf.cache_dir(), "fleet.json")

# `[deck] demo = true` (phosphor demo): no ssh, just plausible readings that
# drift over time so a recording doesn't look like a frozen frame. Not meant
# to look like any one real machine, just a believable one.
DEMO_BASE = {
    "nebula": {"cpu": 16, "mem": 0.34, "memt": 32768,
               "mnt": [("/", 41, "512G"), ("/home", 63, "1.8T")],
               "ctr": ("docker", 7, 0), "temp": 48},
    "forge":  {"cpu": 52, "mem": 0.61, "memt": 65536,
               "mnt": [("/", 77, "930G")],
               "gpu": [{"name": "NVIDIA GeForce RTX 4070", "util": "38",
                        "used": "4200", "total": "12288", "temp": "57"}], "temp": 71},
    "atlas":  {"cpu": 9,  "mem": 0.22, "memt": 16384,
               "mnt": [("/home", 28, "460G")], "temp": 44, "bat": "83|Discharging"},
    "vault":  {"cpu": 3,  "mem": 0.12, "memt": 8192,
               "mnt": [("/mnt/data", 88, "14T"), ("/mnt/backup", 95, "8T")],
               "smart": "0|4"},
    "relay":  {"cpu": 29, "mem": 0.44, "memt": 4096,
               "mnt": [("/", 52, "58G")],
               "ctr": ("podman", 3, 1)},
}

def demo_collect(name):
    b = DEMO_BASE.get(name, DEMO_BASE["atlas"])
    t, off = time.time(), (sum(map(ord, name)) % 7)
    def wobble(base, amp):
        v = base + amp * math.sin(t / 9.0 + off) + random.uniform(-amp * 0.25, amp * 0.25)
        return max(0.0, min(100.0, v))
    cpu = wobble(b["cpu"], max(4, b["cpu"] * 0.3))
    memt = b["memt"]
    memu = int(memt * max(0.02, min(0.97, b["mem"] + random.uniform(-0.03, 0.03))))
    d = {"ok": True, "CPU": int(cpu), "MEMU": memu, "MEMT": memt,
         "LOAD": "%.2f %.2f %.2f" % (cpu/100*4, cpu/100*3.6, cpu/100*3.2),
         "mnt": list(b.get("mnt", [])), "ctr": b.get("ctr"), "gpu": []}
    for g in b.get("gpu", []):
        g = dict(g)
        try: g["util"] = str(int(wobble(int(g["util"]), 15)))
        except ValueError: pass
        d["gpu"].append(g)
    if b.get("temp"):
        d["TEMP"] = str(int(wobble(b["temp"], 3)))
    for k in ("bat", "smart"):
        if b.get(k):
            d[k.upper()] = b[k]
    return d

def tone(p): return PH if p < 60 else (AMB if p < 85 else RED)
def bar(pct, w):
    pct = max(0, min(100, pct)); f = int(round(pct * w / 100.0))
    return tone(pct) + "█"*f + RULE + "░"*(w-f) + RST
def pctc(p): return tone(p) + ("%3d%%" % p) + RST

SLOW_POLL_MS = 3000   # worth calling out: a healthy LAN/tailnet round trip is well under this
DOWN_AFTER = 2        # this many misses in a row: stop giving it the full patience window
CONTROL_PERSIST = "60s"   # outlives one poll (INTERVAL) so the next reuses the same connection

def ssh_cmd(ssh, connect_t):
    """A fresh ssh connection every INTERVAL used to mean a fresh login on
    every host's auth log every 15s. ControlMaster reuses one real
    handshake instead: the master from the first poll stays up (per host,
    %C keys the socket by host+port+user) and every poll after that rides
    it, only reconnecting if it actually dropped."""
    ctrl = os.path.join(deckconf.cache_dir(), "ssh")
    os.makedirs(ctrl, exist_ok=True)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % connect_t,
             "-o", "ControlMaster=auto", "-o", "ControlPersist=" + CONTROL_PERSIST,
             "-o", "ControlPath=" + os.path.join(ctrl, "%C"), ssh, "sh -s"]

def collect(name, ssh, known_down=False):
    """`name` never goes past this function into a log: deck.log is meant
    to be safe to paste into an issue, and a host's name isn't. How long
    each host took lives in `d["ms"]` (STATE, fleet.json, the FLEET card
    itself) instead -- all on-screen or local-only, never in that log.

    `known_down`: this host has already missed DOWN_AFTER polls in a row --
    give it a real chance the first couple of times (a genuine blip
    deserves the full 6s/25s), but a host that's been down for minutes
    doesn't need the whole fleet's round to wait the full window again on
    every single poll just to confirm what every recent poll already
    found: still down. A short probe is enough to notice it came back."""
    t0 = time.time()
    def done(d):
        d["ms"] = int((time.time() - t0) * 1000)
        return d
    connect_t, poll_t = (2, 5) if known_down else (6, 25)
    try:
        script = open(COLLECT).read()
        cmd = ["sh","-s"] if ssh is None else ssh_cmd(ssh, connect_t)
        r = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=poll_t)
        if not r.stdout.strip():
            e = (r.stderr or "no answer").strip().splitlines()
            return done({"ok": False, "err": clean(e[-1])[:24] if e else "no answer"})
        d = {"ok": True, "mnt": [], "ctr": None, "gpu": []}
        for line in r.stdout.splitlines():
            if "=" not in line: continue
            k, v = line.split("=", 1)
            if k == "MNT":
                t, p, s = v.split("|"); d["mnt"].append((t, int(p), s))
            elif k == "GPU":
                f = (v.split("|") + [""] * 5)[:5]
                d["gpu"].append({"name": f[0], "util": f[1],
                                 "used": f[2], "total": f[3], "temp": f[4]})
            elif k == "CTR":
                e, run, st = v.split("|"); d["ctr"] = (e, int(run), int(st))
            elif k in ("CPU","MEMU","MEMT","SVCFAIL"): d[k] = int(v)
            else: d[k] = v
        return done(clean_tree(d))   # a host's answer is data: no escapes reach a screen
    except Exception as e:
        return done({"ok": False, "err": str(e)[:24]})

STATE        = {}
FAILS        = {}   # consecutive failed polls, per host
PREV_OK      = {}   # last known ok/not-ok per host, so a level (still down) never refires
PREV_SVCFAIL = {}   # last known failed-service count per host, same reason
PREV_SMART   = {}   # last known count of disks failing SMART per host, same reason
LAST_ALERT   = {}   # last alert time per host, so a flapping link doesn't flood the phone

def _alert(name, ok, text=None):
    """A host's ok/not-ok flipped (or, with an explicit `text`, some other
    real transition on it -- a service failing, or recovering): push+TTS
    it, off the poller thread so a slow or unreachable ntfy server never
    delays the next poll. Goes through `phosphor notify` like any other
    notification (SYS event, push if [push] is on, TTS if [tts] enabled
    AND fleet_alerts is on, the floating toast if notifier is on) instead
    of duplicating that. One cooldown per host covers every alert kind:
    a host already flapping doesn't also need a second, separate one for
    its services."""
    now = time.time()
    if now - LAST_ALERT.get(name, 0) < 60:      # at most one alert a minute per host
        return
    LAST_ALERT[name] = now
    text = text or (("%s is back" % name) if ok else ("%s is unreachable" % name))
    def run():
        try:
            subprocess.Popen([sys.executable, os.path.join(REPO, "phosphor"), "notify",
                              "--tab", "SYS", "--fleet-alert", text],
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            import dlog
            dlog.event_throttled("FLEET", "alert-failed", str(e)[:60])
    threading.Thread(target=run, daemon=True).start()

def update_host(n, r):
    """One host's fresh poll result: debounce a blip, update STATE, and
    alert on a real ok/not-ok transition. Split out of poller() so it's
    testable without a live ThreadPoolExecutor and real ssh."""
    if not r.get("ok"):
        FAILS[n] = FAILS.get(n, 0) + 1
        prev = STATE.get(n)
        # One failed poll isn't an outage (the network blinks, the host is
        # busy): it takes 2 in a row (~30s) to mark it down, and meanwhile
        # the last good data stays.
        if FAILS[n] < 2 and prev and prev.get("ok"):
            return
    else:
        FAILS[n] = 0
    # A real transition (not the first poll ever, which would otherwise
    # alert about a host that was already down before this session started
    # watching it).
    now_ok = bool(r.get("ok"))
    was_ok = PREV_OK.get(n)
    if was_ok is not None and was_ok != now_ok:
        _alert(n, now_ok)
    PREV_OK[n] = now_ok
    # A service crashing (jellyfin, postgresql, tailscaled...) is a more
    # common self-hosting failure than the whole host going down -- same
    # not-the-first-poll guard, so an already-failed service when we start
    # watching doesn't alert either.
    if now_ok:
        fails = r.get("SVCFAIL", 0)
        was_fails = PREV_SVCFAIL.get(n)
        if was_fails is not None and fails != was_fails:
            if fails and not was_fails:
                _alert(n, False, "%s: %d service%s failed" % (n, fails, "" if fails == 1 else "s"))
            elif was_fails and not fails:
                _alert(n, True, "%s: services back to normal" % n)
        PREV_SVCFAIL[n] = fails
        # A disk failing SMART only ever alerts going bad: a count going
        # back to 0 is a disk swapped out, not news worth a push.
        smart = sensors(r)[2]
        if smart is not None:
            if smart[0] > PREV_SMART.get(n, smart[0]):
                _alert(n, False, "%s: %d disk%s failing SMART" % (n, smart[0], "" if smart[0] == 1 else "s"))
            PREV_SMART[n] = smart[0]
    STATE[n] = r

def poller():
    first = True
    while True:
        t0 = time.time()
        if DEMO:
            for n, _ in HOSTS:
                STATE[n] = demo_collect(n)
        else:
            with ThreadPoolExecutor(max_workers=max(4, len(HOSTS))) as ex:
                futs = {ex.submit(collect, n, s, FAILS.get(n, 0) >= DOWN_AFTER): n for n, s in HOSTS}
                for f in futs:
                    n = futs[f]
                    try: r = f.result()
                    except Exception as e: r = {"ok": False, "err": str(e)[:24]}
                    update_host(n, r)
        # The card shows "polling..." until this first round lands -- always
        # logged once, so `phosphor logs fleet` says exactly how long that
        # was and why (one line per host, from collect()'s own SLOW_POLL_MS).
        ms = int((time.time() - t0) * 1000)
        import dlog
        if first:
            dlog.event("FLEET", "first-poll", "%dms, %d hosts" % (ms, len(HOSTS)))
            first = False
        elif ms > SLOW_POLL_MS:
            dlog.event_throttled("FLEET", "slow-round", "%dms" % ms, every=120)
        write_cache()
        time.sleep(3 if DEMO else INTERVAL)

def write_cache():
    """STATE -> fleet.json, same shape read_state() reads back. Split out
    of poller() so a write can be tested without its infinite loop."""
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"t": time.time(), "hosts": STATE}, f)
        os.replace(tmp, CACHE)
    except Exception as e:
        import dlog
        dlog.event_throttled("FLEET", "cache-write-failed", str(e))

def _stat(pid):
    """(state, ppid, pgrp, tpgid) from /proc/<pid>/stat."""
    s = open("/proc/%d/stat" % pid).read()
    f = s[s.rindex(")") + 2:].split()
    return f[0], int(f[1]), int(f[2]), int(f[5])

def unfreeze_once(session):
    """Resume panes stopped by Ctrl-Z that nothing can wake up.

    In a pane without a shell (yazi, an editor it opened, a TUI) Ctrl-Z
    stops the foreground group and there's no `fg` to bring it back: the
    pane freezes for good. A group that is both stopped AND still the
    terminal's foreground has been abandoned, so SIGCONT it. A shell's
    own job control is untouched: after Ctrl-Z the shell takes the
    foreground back, so its stopped jobs aren't the foreground."""
    me, procs = os.getuid(), {}
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try:
            if os.stat("/proc/" + d).st_uid != me: continue
            procs[int(d)] = _stat(int(d))
        except (OSError, ValueError, IndexError):
            continue
    servers = set()
    for pid in procs:
        try:
            cmd = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
        except OSError:
            continue
        if any(b"zellij" in c for c in cmd[:1]) and b"--server" in cmd \
                and cmd[cmd.index(b"--server") + 1:][:1] and \
                cmd[cmd.index(b"--server") + 1].rstrip(b"/").endswith(b"/" + session.encode()):
            servers.add(pid)
    resumed = set()
    for pid, (state, ppid, pgrp, tpgid) in procs.items():
        if state != "T" or pgrp != tpgid or pgrp in resumed: continue
        p, hops = ppid, 0
        while p and p not in servers and p in procs and hops < 64:
            p, hops = procs[p][1], hops + 1
        if p in servers:
            try:
                os.killpg(pgrp, signal.SIGCONT); resumed.add(pgrp)
            except OSError:
                pass
    return resumed

def unfreezer(session):
    while True:
        try: unfreeze_once(session)
        except Exception as e:
            import dlog
            dlog.event_throttled("FLEET", "unfreeze-failed", str(e)[:60])
        time.sleep(3)

MOUNT_CHECK_S = 20   # background sweep for zombie ~/fleet mounts

def recover_zombie_mount(name, mp):
    """fusermount -uz first, then restart the unit: a fresh rclone can't
    mount over a mountpoint the kernel still considers busy from the dead
    one (see mount_watchdog)."""
    fusermount = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"
    try:
        subprocess.run([fusermount, "-uz", mp], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "--user", "restart", "fleet-%s.service" % name],
                       capture_output=True, timeout=15)
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False

def mount_sweep(names, root):
    """One pass over `~/fleet/<host>` mounts whose SFTP transport died (a
    remote sleeping or changing IP over Tailscale, most often): nothing
    else notices, since the mount stays registered and looks fine to
    `os.path.ismount()` -- only every real access to it fails. Never names
    which host in deck.log, same reasoning as collect(). Split out of
    mount_watchdog() so a sweep can be tested without its infinite loop."""
    recovered = 0
    for name in names:
        mp = os.path.join(root, name)
        if deckconf.mount_zombie(mp) and recover_zombie_mount(name, mp):
            recovered += 1
    if recovered:
        import dlog
        dlog.event("FLEET", "zombie-mount", "recovered %d mount(s)" % recovered)
    return recovered

def mount_watchdog(names, root):
    if not names:
        return
    while True:
        mount_sweep(names, root)
        time.sleep(MOUNT_CHECK_S)

def read_cache():
    """(when it was written, every host's latest poll), straight from
    fleet.json -- the same file glance and the adjutant already read.
    poller() writes it (in this process, for now); the draw loop below only
    ever reads it, so whatever writes it next (a Rust poller, a systemd
    service) needs no change here."""
    try:
        with open(CACHE) as f:
            d = json.load(f)
        return d.get("t", 0), clean_tree(d.get("hosts", {}))
    except (OSError, ValueError, AttributeError):
        return 0, {}

def read_state():
    return read_cache()[1]

def card(name, w, d):
    """One machine, as lines exactly w visible columns wide. `d` is that
    host's own poll result (read_state()[name]), or None before the first
    one lands."""
    inner = w - 4
    up = (d or {}).get("UP", "")
    # the same top border as ui.card(): the name bright, its uptime dim on the right
    title = " " + name.upper() + " "
    tail = (" " + up + " ") if up else ""
    head = (RULE + "╭─" + RST + BLOOM + title + RST
            + RULE + "─"*max(0, w-4-len(title)-len(tail)) + RST
            + MUTE + tail + RST + RULE + "─╮" + RST)
    body = []
    if d is None:
        body = [DIM + "polling..." + RST]
    elif not d.get("ok"):
        err = d.get("err", "?")
        if d.get("ms"):
            err += "  (%.1fs)" % (d["ms"] / 1000.0)
        body = [RED + "unreachable" + RST, DIM + err + RST]
    else:
        bw = max(3, min(18, inner - 10))
        cpu = d.get("CPU", 0)
        body.append(MUTE + "CPU " + RST + bar(cpu, bw) + " " + pctc(cpu))
        mu, mt = d.get("MEMU", 0), d.get("MEMT", 1) or 1
        mp = int(round(mu * 100.0 / mt))
        body.append(MUTE + "RAM " + RST + bar(mp, bw) + " " + pctc(mp))
        body.append(DIM + ("     %.1f / %.0f GiB" % (mu/1024.0, mt/1024.0)) + RST)
        if d.get("LOAD"):
            body.append(MUTE + "LOAD " + RST + FG + d["LOAD"] + RST)
        # fleet.json can be written by either poller, possibly an older
        # build than this code (a Rust binary needs a rebuild to pick up a
        # collect.sh change; Python doesn't) -- SVCFAIL may come through as
        # a plain string from a stale writer that doesn't know it's a
        # number yet. Never trust its type, same spirit as the GPU fields
        # a few lines up.
        try: svcfail = int(d.get("SVCFAIL") or 0)
        except (TypeError, ValueError): svcfail = 0
        if svcfail:
            body.append(RED + "● %d failed" % svcfail + RST)
        if d.get("REBOOT"):
            body.append(AMB + "⟳ reboot pending" + RST)
        upd = updates(d)
        if upd and upd[1]:
            body.append(AMB + "⇪ %d security update%s" % (upd[1], "" if upd[1] == 1 else "s") + RST)
        elif upd and upd[0]:
            body.append(DIM + "⇪ %d update%s" % (upd[0], "" if upd[0] == 1 else "s") + RST)
        temp, bat, smart = sensors(d)
        parts, width = [], 0
        if temp is not None:
            t = "%d°C" % temp
            parts.append(MUTE + "TEMP " + RST + (PH if temp < 70 else AMB if temp < 85 else RED) + t + RST)
            width += 5 + len(t)
        if bat:
            p, st = bat
            arrow = {"Charging": "↑", "Discharging": "↓"}.get(st, "")
            low = st == "Discharging" and p <= 30
            t = "%d%%%s" % (p, arrow)
            parts.append(MUTE + "BAT " + RST + ((RED if p <= LOW_BAT else AMB) if low else PH) + t + RST)
            width += 4 + len(t) + (2 if width else 0)
        if smart and not smart[0] and width + 10 <= inner:
            parts.append(DIM + "SMART ok" + RST)
        if parts:
            body.append("  ".join(parts))
        if smart and smart[0]:
            body.append(RED + "● %d disk%s failing SMART" % (smart[0], "" if smart[0] == 1 else "s") + RST)
        elif smart and width + 10 > inner:
            body.append(DIM + "SMART ok" + RST)
        if d.get("ms", 0) > SLOW_POLL_MS:
            body.append(AMB + "slow poll: %.1fs" % (d["ms"] / 1000.0) + RST)
        for g in d.get("gpu", []):
            short = g["name"].replace("NVIDIA ", "").replace("GeForce ", "")
            short = short.replace(" with Max-Q Design", " MaxQ")
            try: gu = int(g["util"] or 0)
            except ValueError: gu = 0
            body.append(MUTE + "GPU " + RST + bar(gu, bw) + " " + pctc(gu))
            det = ""
            if g["used"] and g["total"]:
                det = "%.1f/%.1f GiB" % (int(g["used"])/1024.0, int(g["total"])/1024.0)
            if g["temp"]: det += ("  " + g["temp"] + "°C")
            body.append("     " + DIM + short[:inner-7] + RST)
            if det: body.append("     " + DIM + det + RST)
        body.append("")
        for t, p, s in d.get("mnt", []):
            lbl = t if len(t) <= inner-11 else "…" + t[-(inner-12):]
            body.append(FG + ("%-*s" % (inner-11, lbl)) + RST + pctc(p) + " " + DIM + ("%5s" % s) + RST)
        body.append("")
        c = d.get("ctr")
        if c:
            eng, run, st = c
            body.append(DIM + ("%-8s" % eng) + RST + PH + ("%4d ✓" % run) + RST
                        + "  " + (RED if st else DIM) + ("%3d ✗" % st) + RST)
        else:
            body.append(DIM + "no containers" + RST)
    return head, body

# Keys over a card: pick one (arrows, Tab, a tap), then open something on
# that machine in a tab of its own. Nothing here changes the host itself:
# a shell, its logs, a read-only look through `phosphor triage`, or its
# containers (`phosphor containers`, which asks before touching one).
ACTIONS = [("s", "ssh"), ("l", "logs"), ("t", "triage"), ("c", "containers")]
# ...and one that stays in this pane: the card's last 24 hours (lib/history.py)
HISTORY = ("h", "history")

def action_tab(key, name, target):
    """(tab name, pane spec) for `key` over the card of `name` (its ssh
    target, None for this machine), or None for a key that isn't one."""
    if key == "s":
        return name.upper(), ({"ssh": target} if target else {"cwd": HOME})
    if key == "l":
        import tail
        argv = tail.remote_argv(None)
        if target:
            argv = ["ssh", "-t", target] + argv
        label = ("TAIL-" + name).upper()[:24]
        return label, {"_run": argv, "_name": label, "reconnect": bool(target)}
    if key == "t":
        return ("TRIAGE-" + name).upper()[:24], {"cmd": "phosphor triage", "args": [name]}
    if key == "c":
        return ("CTR-" + name).upper()[:24], {"cmd": "phosphor containers", "args": [name]}
    return None

def open_action(key, name, target):
    """Open the tab for `key` next to this one. A message either way."""
    if DEMO and key != "c":        # containers has made-up ones for the demo
        return "the demo's machines aren't real: nothing to open"
    if not os.environ.get("ZELLIJ"):
        return "open it from inside the deck"
    got = action_tab(key, name, target)
    if not got:
        return ""
    import gen, newtab
    label, spec = got
    label = newtab.unique(label, newtab.taken_names())
    d = os.path.join(deckconf.cache_dir(), "apps")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s-%s.kdl" % (label.lower(), time.strftime("%Y%m%d-%H%M%S")))
    with open(lay, "w") as f:
        f.write(gen.tab_kdl({"name": label, "panes": [spec]}, gen.Ctx(deckconf.load()[0] or {}),
                            "phosphor fleet"))
    newtab.zj("new-tab", "--layout", lay, "--name", label)
    return "opened " + label

def card_at(x, y, cw, gap, per_row, h, n):
    """The card index under a tap at pane column x, row y (both 1-based),
    or None: the gap between cards, or below the last one."""
    col, cx = divmod(x - 1, cw + gap)
    if cx >= cw or col >= per_row:
        return None
    i = ((y - 1) // h) * per_row + col
    return i if 0 <= i < n else None

def move(sel, k, per_row, n):
    """The card an arrow or Tab lands on; the first one when none is picked."""
    if sel is None:
        return 0
    step = {"\x1b[C": 1, "\t": 1, "\x1b[D": -1, "\x1b[B": per_row, "\x1b[A": -per_row}.get(k, 0)
    j = sel + step
    return j if 0 <= j < n else sel

def grid(cols, rows, state, sel=None):
    """The cards, laid out for a pane cols x rows: (lines, card width,
    cards per row, card height). No line is wider than the pane."""
    n, gap = len(HOSTS), 1
    # never wider than the pane: zellij wraps a longer line, and a
    # phone's SYS (the adjutant beside fleet) can leave it ~20 columns
    cw = min(cols, 40, max(24, (cols - (n-1)*gap) // n))
    raw = [card(h[0], cw, state.get(h[0])) for h in HOSTS]
    bh = max(len(b) for _, b in raw)
    inner = cw - 4
    cards = []
    for i, (head, body) in enumerate(raw):
        edge = BLOOM if i == sel else RULE      # the picked card's border lights up
        body = body + [""]*(bh - len(body))
        c = [head.replace(RULE, edge, 1)]
        for b in body:
            c.append(edge + "│" + RST + " " + pad(vcut(b, inner), inner) + " " + edge + "│" + RST)
        c.append(edge + "╰" + "─"*(cw-2) + "╯" + RST)
        cards.append(c)
    per_row = max(1, (cols + gap) // (cw + gap))
    h = len(cards[0])
    out = []
    for i in range(0, n, per_row):
        grp = cards[i:i+per_row]
        for r in range(h):
            out.append((" "*gap).join(g[r] for g in grp))
    # Never more lines than the pane has: with many machines the
    # cards get cut at the bottom but the footer stays visible.
    return [vcut(o, cols) for o in out[:max(0, rows - 2)]], cw, per_row, h

def footer(n, sel, msg):
    """The bottom line, and {column range: key} for tapping its hints."""
    base = " phosphor fleet · " + time.strftime("%H:%M:%S") + "  ·  " + str(n) + " hosts  ·  every " \
        + str(INTERVAL) + "s"
    if sel is None:
        text = base + "  ·  tap a machine"
        return DIM + text + RST + ("  " + AMB + msg + RST if msg else ""), {}
    # picked: just what the keys do, short enough for a phone's width
    out, taps, x = " " + FG + HOSTS[sel][0] + RST, {}, 1 + len(HOSTS[sel][0])
    for k, what in ACTIONS + [HISTORY, ("Esc", "")]:
        piece = "  " + k + (" " + what if what else "")
        taps[(x + 3, x + len(piece))] = "\x1b" if k == "Esc" else k
        out += "  " + AMB + k + RST + (" " + FG + what + RST if what else "")
        x += len(piece)
    if msg:
        out += "  " + DIM + "· " + RST + AMB + msg + RST
    return out, taps

def history_footer(name):
    """The bottom line over a host's history, and its taps."""
    out, taps, x = " " + FG + name + RST, {}, 1 + len(name)
    for k, what, key in (("← →", "another host", "\t"), ("Esc", "back", "\x1b")):
        piece = "  " + k + " " + what
        taps[(x + 3, x + len(piece))] = key
        out += "  " + AMB + k + RST + " " + FG + what + RST
        x += len(piece)
    return out, taps

class RustPoller:
    """Supervises the optional `phosphor-fleet-poll` subprocess: relaunches
    it if it dies, and hot-reloads it (terminate, respawn) the moment the
    binary on disk changes -- a rebuild takes effect within one redraw
    frame, without touching this pane or the rest of the deck. A crash
    loop (3 deaths inside 2s, not a deliberate rebuild) gives up on Rust
    for the rest of this pane's life and starts the Python thread instead,
    so the panel keeps updating either way."""
    MAX_RAPID_FAILS = 3
    RAPID_WINDOW = 2.0

    def __init__(self, path):
        self.path = path
        self.proc = None
        self.mtime = None
        self.spawned_at = 0.0
        self.rapid_fails = 0
        self.gave_up = False
        self._spawn("start")

    def _spawn(self, reason):
        try:
            self.mtime = os.path.getmtime(self.path)
        except OSError:
            pass
        import dlog
        try:
            self.proc = subprocess.Popen([self.path], stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.spawned_at = time.time()
            dlog.event("FLEET", "rust-poller", "%s, pid=%d" % (reason, self.proc.pid))
        except OSError as e:
            self.proc = None
            dlog.event("FLEET", "rust-poller-failed", str(e)[:60])
            self._give_up()

    def _give_up(self):
        if self.gave_up:
            return
        self.gave_up = True
        import dlog
        dlog.event("FLEET", "rust-poller-gave-up", "falling back to the python thread")
        threading.Thread(target=poller, daemon=True).start()

    def tick(self):
        """Call every redraw frame: notices a crash or a rebuilt binary."""
        if self.gave_up or self.proc is None:
            return
        died = self.proc.poll() is not None
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = self.mtime
        changed = mtime is not None and mtime != self.mtime
        if not died and not changed:
            return
        if changed and not died:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if died and not changed:
            self.rapid_fails = self.rapid_fails + 1 if time.time() - self.spawned_at < self.RAPID_WINDOW else 1
            if self.rapid_fails > self.MAX_RAPID_FAILS:
                self._give_up()
                return
        else:
            self.rapid_fails = 0
        self._spawn("rebuilt" if changed else "restarted")

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


def rust_current(path):
    """Whether a `phosphor-fleet-poll` binary runs this checkout's
    collect.sh: it embeds the script when it's built, and an installed one
    is never replaced by an update, so an old binary would keep polling
    with an old script (no SMART, no updates...) for good."""
    try:
        with open(COLLECT, "rb") as f:
            script = f.read()
        with open(path, "rb") as f:
            return script in f.read()
    except OSError:
        return False

def start_poller():
    """A RustPoller (supervising an optional `phosphor-fleet-poll`
    subprocess, its own INTERVAL, its own ssh) if one is installed writing
    the same fleet.json -- else the Python thread this file has always run.
    DEMO always gets the Python poller: the Rust one refuses `[deck] demo =
    true` on purpose, so its fabricated readings only ever come from here,
    and a binary built from another collect.sh (rust_current) gets it too.

    Returns the RustPoller to tick() every frame and stop() on the way out,
    or None (a thread, daemon already, needs neither)."""
    if not DEMO:
        rust = deckconf.exe("phosphor-fleet-poll")
        if rust and rust_current(rust):
            return RustPoller(rust)
        if rust:
            import dlog
            dlog.event("FLEET", "rust-stale", "phosphor-fleet-poll predates collect.sh: Python polls")
    threading.Thread(target=poller, daemon=True).start()
    return None

def main():
    global HOSTS, DEMO
    prof = deckconf.load()[0]
    HOSTS = deckconf.fleet_hosts(prof)
    DEMO = bool(((prof or {}).get("deck") or {}).get("demo", False))

    # A kind of screen's own session (deck-phone) only reads fleet.json: the
    # deck's fleet polls and sweeps the mounts, once, not once per screen.
    screen = bool(os.environ.get("PHOSPHOR_SCREEN"))
    rust_poller = None if screen else start_poller()
    # the day's history: recorded once too, by the deck's own fleet
    import history
    recorder = None if screen else history.Recorder()
    if DEMO and not screen and not os.path.exists(history.path()):
        history.seed_demo([h[0] for h in HOSTS], DEMO_BASE)
    # its own session: a kind of screen's (deck-phone) marks its own tabs
    sess = os.environ.get("ZELLIJ_SESSION_NAME") or \
        ((deckconf.load()[0] or {}).get("deck") or {}).get("session", "deck")
    threading.Thread(target=unfreezer, args=(sess,), daemon=True).start()
    import mentions
    threading.Thread(target=mentions.marker, args=(sess,), daemon=True).start()
    mount_names = [h["name"] for h in deckconf.mount_hosts(prof)]
    if not screen:
        threading.Thread(target=mount_watchdog, args=(mount_names, deckconf.mount_root(prof)),
                         daemon=True).start()
    tty = sys.stdin.isatty()
    sys.stdout.write("\x1b[?1049h\x1b[?25l" + ("\x1b[?1000h\x1b[?1006h" if tty else ""))
    sel, msg, msg_until, geo, hist = None, "", 0, None, None
    try:
        while True:
            if rust_poller is not None:
                rust_poller.tick()
            cols, rows = shutil.get_terminal_size((80, 24))
            n, gap = len(HOSTS), 1
            if sel is not None and sel >= n:
                sel = None
            if hist is not None and hist >= n:
                hist = None
            t, state = read_cache()
            if recorder is not None:
                recorder.feed(state, t)
            if hist is not None:
                name = HOSTS[hist][0]
                out = history.view(name, history.load().get(name, []), cols, rows - 2)
                out += [""] * max(0, rows - 2 - len(out))
                cw = per_row = h = 0
            else:
                out, cw, per_row, h = grid(cols, rows, state, sel)
            out.append("")
            if msg and time.time() > msg_until:
                msg = ""
            line, taps = history_footer(HOSTS[hist][0]) if hist is not None else footer(n, sel, msg)
            out.append(vcut(line, cols))
            geo = (cw, gap, per_row, h, len(out))
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            if not tty:
                time.sleep(1); continue
            k = getkey(1)
            if isinstance(k, tuple):                 # a tap: a card, or a hint on the last line
                _, btn, x, y, pressed = k
                if btn != 0 or not pressed:
                    continue
                if y == geo[4]:
                    k = next((v for (a, b), v in taps.items() if a <= x <= b), None)
                elif hist is not None:
                    continue
                else:
                    if y <= geo[4] - 2:
                        hit = card_at(x, y, cw, gap, per_row, h, n)
                        if hit is not None:
                            sel = hit
                    continue
            if k == "\x03":
                break
            if hist is not None:                     # over a host's history
                if k in ("\x1b[C", "\t", "\x1b[B"):
                    hist = (hist + 1) % n
                elif k in ("\x1b[D", "\x1b[A"):
                    hist = (hist - 1) % n
                elif k in ("\x1b", "q", "h"):
                    sel, hist = hist, None
                continue
            if k in ("\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\t"):
                sel = move(sel, k, per_row, n)
            elif k == "\x1b":
                sel = None
            elif k == HISTORY[0]:
                if sel is None:
                    msg, msg_until = "pick a machine first: arrows or a tap", time.time() + 5
                else:
                    hist = sel
            elif k in [a for a, _ in ACTIONS]:
                if sel is None:
                    msg = "pick a machine first: arrows or a tap"
                else:
                    msg = open_action(k, HOSTS[sel][0], HOSTS[sel][1])
                msg_until = time.time() + 5
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(("\x1b[?1006l\x1b[?1000l" if tty else "") + "\x1b[?1049l\x1b[?25h\n")
        if rust_poller is not None:
            rust_poller.stop()
        if recorder is not None:
            recorder.flush()

if __name__ == "__main__":
    main()
