#!/usr/bin/env python3
"""Deck logs: a crash keeps its traceback, a hang is recorded, a trace
turns itself off on its own, and a note's text never lands in either.

    python3 tests/log-check.py
"""
import os, sys, tempfile, pty, select, time, struct, fcntl, termios, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.environ.pop("ZELLIJ", None)
import dlog

# -- the base log: events, per-tool filtering, a capped size --
dlog.event("ONE", "exit", "1")
dlog.event("TWO", "hung")
check("events land in deck.log", os.path.exists(dlog.LOG))
check("tail_for keeps only that tool's lines", [l.split()[2] for l in dlog.tail_for("ONE")] == ["ONE"])

try:
    1 / 0
except ZeroDivisionError:
    dlog.crash("ONE")
lines = dlog.tail(dlog.LOG, 20)
check("a crash's traceback is kept, not lost",
      any("ZeroDivisionError" in l for l in lines) and any("Traceback" in l for l in lines))

open(dlog.LOG, "w").write("x" * (dlog.CAP + 500) + "\n")
dlog.event("CAP", "exit", "0")
check("the base log stays size-capped", os.path.getsize(dlog.LOG) < dlog.CAP + 500)
open(dlog.LOG, "w").close()

# -- a throttled event: once, not once per tick of a redraw loop --
dlog.event_throttled("LOOP", "stuck", "first", every=300)
dlog.event_throttled("LOOP", "stuck", "second", every=300)
check("a throttled event only lands once", len(dlog.tail_for("LOOP")) == 1)
dlog._throttled[("LOOP", "stuck")] -= 301
dlog.event_throttled("LOOP", "stuck", "third", every=300)
check("and again once its window passed", len(dlog.tail_for("LOOP")) == 2)

# -- trace: off by default, on for a while, off again by itself --
check("nothing traces by default", not dlog.tracing("PROBE"))
dlog.start_trace("PROBE", minutes=30)
check("phosphor trace turns one on", dlog.tracing("PROBE"))
check("and lists it as active", any(t == "PROBE" for t, _ in dlog.active_traces()))
dlog.trace("PROBE", "a verbose line")
check("a verbose line lands in its own file", "a verbose line" in open(dlog.tracefile("PROBE")).read())
with open(dlog.flag("PROBE"), "w") as f:
    f.write(str(time.time() - 1))            # the ~30 minutes already passed
check("a trace turns itself off", not dlog.tracing("PROBE"))
check("and clears its own flag", not os.path.exists(dlog.flag("PROBE")))

# -- a mention-hook that never prints still leaves a trace of a crash --
open(dlog.LOG, "w").close()
import io, mentions
real_stdin = sys.stdin
sys.stdin = io.StringIO("not json")
try:
    out_buf = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, out_buf
    try:
        rc = mentions.hook()
    finally:
        sys.stdout = real_stdout
finally:
    sys.stdin = real_stdin
check("the hook still returns 0 and prints nothing", rc == 0 and out_buf.getvalue() == "")
check("but the crash is in deck.log", any("MENTIONS" in l and "crash" in l for l in dlog.tail(dlog.LOG, 20)))

# -- phosphor web off logs whichever of its steps fails --
open(dlog.LOG, "w").close()
import web
webprofile = os.path.join(tmp, "web-profile.toml")
open(webprofile, "w").write("[deck]\nsession = \"probe\"\n")
os.environ["PHOSPHOR_PROFILE"] = webprofile
real_ts, real_zj = web.ts, web.zj
web.ts = lambda *a: (_ for _ in ()).throw(OSError("no tailscale here"))
web.zj = lambda *a: (_ for _ in ()).throw(OSError("no zellij here"))
try:
    web.off()
finally:
    web.ts, web.zj = real_ts, real_zj
    os.environ.pop("PHOSPHOR_PROFILE", None)
check("a failed 'web off' step lands in deck.log",
      sum(1 for l in dlog.tail(dlog.LOG, 20) if "WEB" in l and "off-step-failed" in l) >= 2)

# -- a redraw-loop failure is throttled, not logged once per tick --
open(dlog.LOG, "w").close()
import adjutant
fleet_json = os.path.join(tmp, ".cache", "phosphor", "fleet.json")
os.makedirs(os.path.dirname(fleet_json), exist_ok=True)
open(fleet_json, "w").write("not json")
adjutant.fleet_alert(); adjutant.fleet_alert()
check("a broken fleet.json logs once, throttled",
      sum(1 for l in dlog.tail(dlog.LOG, 20) if "ADJUTANT" in l and "fleet-json-failed" in l) == 1)

# -- privacy: a config that fails to parse is logged, but never quoted --
open(dlog.LOG, "w").close()
import privacy
mm_dir = os.path.join(tmp, ".config", "matterhorn")
os.makedirs(mm_dir, exist_ok=True)
open(os.path.join(mm_dir, "config.ini"), "w").write(
    "[mattermost\nhost = SECRET-server.example\nuser = secret-login\n")   # missing ']': fails to parse
privacy.tokens()
check("a bad matterhorn config is logged", any("PRIVACY" in l and "matterhorn-config-failed" in l
                                               for l in dlog.tail(dlog.LOG, 20)))
check("but never the host/login it names, even in the exception text",
      "SECRET-server" not in open(dlog.LOG).read() and "secret-login" not in open(dlog.LOG).read())

# -- privacy: no git on PATH doesn't crash the scan, just finds less --
real_run = privacy.subprocess.run
def no_git(cmd, *a, **kw):
    if isinstance(cmd, list) and cmd and cmd[0] == "git":
        raise FileNotFoundError(2, "No such file or directory", "git")
    return real_run(cmd, *a, **kw)
privacy.subprocess.run = no_git
try:
    check("tokens() survives a machine with no git installed", isinstance(privacy.tokens(), dict))
finally:
    privacy.subprocess.run = real_run

# -- phosphor run, in a real pty: a crash and a hang both get recorded --
def probe(name, code, seconds, hang_seconds="0.6", resize=False):
    env = dict(os.environ, PHOSPHOR_HANG_SECONDS=hang_seconds)
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor"), "run",
                                   "--name", name, "--", sys.executable, "-c", code], env)
    out, end, resized = b"", time.time() + seconds, False
    while time.time() < end:
        if resize and not resized and time.time() > end - seconds + 0.5:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 40, 0, 0)); resized = True
        if select.select([fd], [], [], 0.1)[0]:
            try: out += os.read(fd, 4096)
            except OSError: break
    try:
        os.killpg(pid, 9); os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    return out.decode("utf-8", "replace")

open(dlog.LOG, "w").close()
probe("REALEXIT", "import sys; sys.exit(7)", 2)
check("a non-zero exit lands in deck.log",
      any("REALEXIT" in l and "exit" in l and l.strip().endswith("7") for l in dlog.tail(dlog.LOG, 20)))

open(dlog.LOG, "w").close()
FROZEN = "import signal,time; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGWINCH}); time.sleep(60)"
probe("REALHANG", FROZEN, 6, resize=True)
check("a hang lands in deck.log", any("REALHANG" in l and "hung" in l for l in dlog.tail(dlog.LOG, 20)))

# -- phosphor logs / trace, from the command line --
out = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "logs", "realexit"],
                      capture_output=True, text=True, env=os.environ).stdout
check("phosphor logs TOOL filters to it", "REALEXIT" in out and "REALHANG" not in out)

# -- privacy: a note's own text and title never end up in the base log --
notefile = os.path.join(tmp, "priv-notes.md")
subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "note", "--file", notefile,
                "a very secret title, not for any log"], env=os.environ)
check("the note itself was written", "secret title" in open(notefile).read())
check("but never the base log", "secret title" not in open(dlog.LOG).read())

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
