"""phosphor restart, up, down and attach: the deck's session, from the
brain. Kept out of the dispatcher so it reads as a table of commands, and so
hotswap can tell this code apart from the dispatcher's own."""
import os, sys
import deckconf, proc
from ui import DIM as DIM_, RST as RST_

HERE = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
PHOSPHOR = os.path.join(os.path.dirname(HERE), "phosphor")
RESTARTING = os.path.expanduser("~/.cache/phosphor/restarting")

def load_profile():
    prof, p = deckconf.load()
    if prof is None:
        print("can't read the profile (%s): %s" % (p, deckconf.ERR))
    return prof, p

def session_live(zj, sess):
    """The session exists and isn't a dead one left in zellij's cache."""
    import subprocess
    try:
        out = subprocess.run([zj, "list-sessions", "-n"], capture_output=True, text=True, timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return False
    return any(l.split()[:1] == [sess] and "EXITED" not in l for l in out.splitlines())

def session_gone(zj, sess):
    """Not just not-live: not even a dead entry left in zellij's cache."""
    import subprocess
    try:
        out = subprocess.run([zj, "list-sessions", "-n"], capture_output=True, text=True, timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return True                          # can't tell either way: don't block on it
    return not any(l.split()[:1] == [sess] for l in out.splitlines())

def poll_until(check, timeout, interval=0.15):
    """True as soon as `check()` is, sleeping `interval` between tries --
    same worst case as a blind `sleep(timeout)`, usually a lot less: down
    and up used to spend a fixed handful of seconds waiting on things that
    are almost always already done well before the deadline."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(interval)
    return check()


def run(cmd, argv):
    """restart, up, down, attach or deck (attach's other name)."""
    rc = viewer(cmd)
    if rc is not None:
        return rc
    if cmd in ("attach", "deck"):
        return attach(argv)
    return updown(cmd)

def viewer(cmd):
    """A viewer holds no session: these belong to the brain. attach just
    runs this machine's connect command instead. None on the brain."""
    prof, _ = load_profile()
    loc = next((h for h in (prof or {}).get("hosts", []) if h.get("local")), None)
    if loc and loc.get("role") != "brain":
        brain = next((h["name"] for h in prof.get("hosts", []) if h.get("role") == "brain"), "the brain")
        launcher = os.path.expanduser("~/.local/bin/%s" % ((prof.get("deck") or {}).get("command", "deck")))
        if cmd in ("attach", "deck") and os.path.exists(launcher):
            os.execv(launcher, [launcher])
        print("  this machine is a viewer: the deck lives on %s." % brain)
        print("  get in with: %s   (%s runs over there)" % (os.path.basename(launcher), cmd))
        return 1

def updown(cmd):
    import subprocess as _sp, time as _t, signal as _sig, re as _re
    prof, _ = load_profile()
    sess = ((prof or {}).get("deck") or {}).get("session", "deck")
    # Run from a pane of the deck itself (a shell, an assistant), killing
    # the session would kill this command halfway, after it stopped the
    # watchdog: the deck would stay down. Detach and let it finish.
    if cmd in ("restart", "down") and os.environ.get("ZELLIJ_SESSION_NAME") == sess \
            and not os.environ.get("PHOSPHOR_DETACHED"):
        logp = os.path.expanduser("~/.cache/phosphor/%s.log" % cmd)
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        env = dict(os.environ, PHOSPHOR_DETACHED="1")
        env.pop("ZELLIJ", None); env.pop("ZELLIJ_SESSION_NAME", None); env.pop("ZELLIJ_PANE_ID", None)
        _sp.Popen([sys.executable, PHOSPHOR, cmd], start_new_session=True,
                  env=env, stdin=_sp.DEVNULL, stdout=open(logp, "w"), stderr=_sp.STDOUT)
        print("  inside the deck: %s runs detached, this pane will close." % cmd)
        if cmd == "restart":
            print("  every screen goes back in by itself when the deck is up again.")
        print("  " + DIM_ + "log: " + logp + RST_)
        return 0
    zj = proc.zellij()
    if not zj:
        print("  zellij isn't installed: run install.sh again (it fetches it)")
        return 1
    R = lambda *a: _sp.run(list(a), capture_output=True, text=True, timeout=30)

    def procs():
        # /proc directly, not `ps`: it isn't installed everywhere the
        # deck (or its CI) runs, and /proc/PID/stat is already how the
        # parent-chain walk above reads it.
        r = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    args = f.read().replace(b"\0", b" ").strip().decode("utf-8", "replace")
            except OSError:
                continue
            if args: r.append((int(pid), args))
        return r

    if cmd == "restart":
        # Every screen gets kicked out; this tells their `deck` to wait
        # for the new session and go back in (see attach).
        os.makedirs(os.path.dirname(RESTARTING), exist_ok=True)
        open(RESTARTING, "w").close()
    if cmd in ("restart", "down"):
        # The timer first: otherwise it recreates the session mid-cleanup
        # and you end up with two of everything.
        R("systemctl", "--user", "stop", "%s.timer" % sess, "%s.service" % sess)
        import kinds
        screens_ = kinds.all_sessions(prof)       # deck-phone, deck-eink...
        for s_ in [sess] + screens_:
            R(zj, "kill-session", s_)
        poll_until(lambda: not any(session_live(zj, s_) for s_ in [sess] + screens_), 2)
        for s_ in [sess] + screens_:
            R(zj, "delete-session", s_)
        gone = poll_until(lambda: all(session_gone(zj, s_) for s_ in [sess] + screens_), 5)
        # This process and its whole parent chain match the patterns too.
        protect, cur = set(), os.getpid()
        while cur and cur != 1:
            protect.add(cur)
            try:
                cur = int(open("/proc/%d/stat" % cur).read().split()[3])
            except Exception:
                break
        import reap
        for sg in (_sig.SIGTERM, _sig.SIGKILL):
            tgt = [pid for s_ in [sess] + screens_ for pid, _a in reap.targets(procs(), s_, protect)]
            for pid in tgt:
                try: os.kill(pid, sg)
                except Exception: pass
            poll_until(lambda: not any(reap.targets(procs(), s_, protect) for s_ in [sess] + screens_), 2)
        left = [t for s_ in [sess] + screens_ for t in reap.targets(procs(), s_, protect)]
        # Proof that the old deck is really gone before a new one starts:
        # otherwise new code on disk runs next to old panes still alive.
        svc = R("systemctl", "--user", "is-active", "%s.service" % sess).stdout.strip()
        problems = reap.down_problems(gone, svc, left, sess)
        import dlog
        if problems:
            print("  the old deck isn't fully down: %s" % (
                "no new one started" if cmd == "restart" else "check it before phosphor up"))
            for p in problems:
                print("    " + p)
            print("  " + DIM_ + "the watchdog stays off. Once they're gone: phosphor %s" % cmd + RST_)
            dlog.event("deck", "%s-stopped" % cmd, "problems=%d leftovers=%d" % (len(problems), len(left)))
            try: os.remove(RESTARTING)
            except OSError: pass
            return 1
        for s_ in screens_:
            kinds.forget(s_)          # a screen's `deck` makes it again when it comes back
        print("  session down%s · leftovers: 0" % (
            (" (and %s)" % ", ".join(screens_)) if screens_ else ""))
        if cmd == "down":
            dlog.event("deck", "down", "leftovers=0")
            print("  " + DIM_ + "the timer is stopped: phosphor up brings it back" + RST_)
            return 0

    R("systemctl", "--user", "daemon-reload")
    # enabled, so it comes back after a reboot (with linger)
    R("systemctl", "--user", "enable", "%s.service" % sess, "%s.timer" % sess)
    udir = os.path.expanduser("~/.config/systemd/user")
    mounts = [u for u in (os.listdir(udir) if os.path.isdir(udir) else [])
              if u.startswith(("fleet-", "tunnel-")) and u.endswith(".service")]
    if mounts:
        R("systemctl", "--user", "enable", "--now", *mounts)
    R("systemctl", "--user", "start", "%s.service" % sess)
    # A loaded or slow machine can take a while to lay the deck out:
    # wait for its tabs, not just for the session's name, up to a minute.
    tabs, t0 = 0, _t.time()
    while _t.time() - t0 < 60:
        if session_live(zj, sess):
            try: tabs = R(zj, "-s", sess, "action", "dump-layout").stdout.count("    tab name=")
            except _sp.TimeoutExpired: tabs = 0
            if tabs: break
        _t.sleep(0.3)
    _t.sleep(2)
    R("systemctl", "--user", "start", "%s.timer" % sess)
    print("  session up: %d tabs · timer: %s"
          % (tabs, R("systemctl", "--user", "is-active", "%s.timer" % sess).stdout.strip()))
    try: os.remove(RESTARTING)
    except OSError: pass
    # Compare with what the layout actually launches (the new-tab menu
    # template aside): a missing pane and a duplicated one both matter.
    bad = False
    try:
        lay = open(os.path.expanduser("~/.config/zellij/layouts/%s.kdl" % sess)).read()
        lay = _re.sub(r"(?s)new_tab_template \{.*?\n    \}\n", "", lay)
    except OSError:
        lay = ""
    for name in ("adjutant", "pulse", "fleet", "keys", "store", "notes", "mentions", "panel"):
        want = len(_re.findall(r'phosphor" "%s"' % name, lay))
        if not want: continue
        # the program, not the `phosphor run` watching over it
        n = sum(1 for _, a in procs() if ("phosphor %s" % name) in a and " run " not in a)
        note = "" if n == want else ("   <- missing" if n < want else "   <- duplicate")
        if note: bad = True
        print("    %-10s %d%s" % (name, n, note))
    # By name alone, not scoped to sess: on a machine that's also running
    # a real deck (this checkout's own tests, run on the brain, always
    # are) every one of these matches twice and falsely calls it a
    # duplicate. ZELLIJ_SESSION_NAME is the same mark reap.targets() uses.
    import reap
    mark = ("ZELLIJ_SESSION_NAME=%s" % sess).encode()
    for name in ("matterhorn", "yazi", "btop", "ctop", "gping"):
        n = sum(1 for pid, a in procs()
                if os.path.basename(a.split()[0]) == name and mark in reap.env_of(pid))
        if n > 1:
            bad = True; print("    %-10s %d   <- duplicate" % (name, n))
    import dlog
    dlog.event("deck", cmd, "tabs=%d bad=%s" % (tabs, bad))
    if not os.environ.get("ZELLIJ"):
        print("  " + DIM_ + "get in: " + RST_ + ((prof or {}).get("deck") or {}).get("command", "deck"))
    return 1 if bad else 0

def attach(argv):
    if os.environ.get("ZELLIJ"):
        print("  you're already inside a zellij session (the deck?): no need to attach")
        return 1
    import kinds
    prof, _ = load_profile()
    sess = ((prof or {}).get("deck") or {}).get("session", "deck")
    # `deck --screen phone`: a kind with a [screens.phone] block gets its
    # own session (see lib/kinds.py); any other kind, the deck's.
    kind = kinds.arg(argv)[0]
    if kind not in kinds.kinds(prof):
        kind = ""
    target = kinds.session(prof, kind) if kind else sess
    zj = proc.zellij()
    if not zj:
        print("  zellij isn't installed: run install.sh again (it fetches it)")
        return 1
    # First time in: thirty seconds of orientation, then never again.
    mark = os.path.expanduser("~/.local/share/phosphor/.welcomed")
    if os.path.exists(mark):
        import panel, splash
        panel.mark("returned")
        splash.show(prof)
    elif sys.stdin.isatty():
        import welcome
        for l in welcome.lines(prof): print(l)
        try: input(welcome.PROMPT)
        except (EOFError, KeyboardInterrupt): print(); return 1
        os.makedirs(os.path.dirname(mark), exist_ok=True); open(mark, "w").close()
    import subprocess as _sp, time as _t
    # Terminals name the tab after the foreground program (Konsole: %n),
    # and that's this process: python3. Call it what you typed instead.
    word = ((prof or {}).get("deck") or {}).get("command", "deck")
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, word.encode()[:15], 0, 0, 0)     # PR_SET_NAME
    except Exception:
        pass
    if sys.stdout.isatty():
        sys.stdout.write("\x1b]0;%s\x07" % word); sys.stdout.flush()
    def restarting():
        try: return _t.time() - os.path.getmtime(RESTARTING) < 180
        except OSError: return False
    # Right after boot, `phosphor up` or the watchdog, the session may
    # not exist yet: wait for it instead of zellij's "No session found".
    if not session_live(zj, sess) and _sp.run(
            ["systemctl", "--user", "is-active", "-q", "%s.service" % sess, "%s.timer" % sess]).returncode == 0:
        print("  the deck is starting...")
        poll_until(lambda: session_live(zj, sess), 90)
    def screen_up():
        """A kind's session comes with the deck: made the first time
        that screen comes in (and again after a restart took it down),
        only while the deck itself is up."""
        if not kind or session_live(zj, target) or not session_live(zj, sess):
            return
        if not kinds.create(zj, prof, kind):
            print("  couldn't make the %s session: phosphor gen, then deck again" % kind)
            return
        poll_until(lambda: session_live(zj, target), 15)
    while True:
        screen_up()
        rc = _sp.call([zj, "attach", target])
        if not restarting():
            return rc
        # kicked out by `phosphor restart`: wait for the new deck, go back in
        print("\n  the deck is restarting: you'll be back in by yourself...")
        if not poll_until(lambda: session_live(zj, sess) and not restarting(), 180):
            print("  it isn't back yet: try deck again in a minute")
            return 1
