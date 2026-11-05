#!/usr/bin/env python3
"""[clipboard] sync: copy on one screen, paste on another.

    python3 tests/clipsync-check.py

Two fake screens through a throwaway brain: each is the real watcher
(`phosphor clipsync --script`) over a fake xclip that keeps its clipboard
in a folder, linked by the real `phosphor clipsync` to a hub whose socket
lives in a temporary XDG_RUNTIME_DIR, with a profile of its own. No ssh,
no zellij, nothing of the live deck. Also: the link and the hub alone
(relay, no echo to the sender, the cap, one copy of a repeated clip, sync
off), and every generated `deck` script still parses with the line in.
"""
import base64, json, os, shutil, signal, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
PH = os.path.join(ROOT, "phosphor")

fails = []
def need(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp(prefix="clipsync-")
prof = os.path.join(tmp, "deck.toml")
def profile(sync, kb=1):
    with open(prof, "w") as f:
        f.write('[deck]\nsession = "probe"\n\n[clipboard]\nsync = %s\nmax_kb = %d\n' % ("true" if sync else "false", kb))
profile(True)
env = {k: v for k, v in os.environ.items()
       if not k.startswith(("ZELLIJ", "SSH_", "WAYLAND", "DISPLAY", "PHOSPHOR"))}
env.update(HOME=tmp, XDG_RUNTIME_DIR=os.path.join(tmp, "run"), PHOSPHOR_PROFILE=prof)
os.makedirs(env["XDG_RUNTIME_DIR"], mode=0o700)

def until(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()

def b64(s):
    return base64.b64encode(s.encode()).decode()

procs = []
try:
    # ── the link and the hub alone ────────────────────────────────────────
    def link():
        p = subprocess.Popen([sys.executable, PH, "clipsync"], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(p.stdout.fileno(), False)
        procs.append(p)
        return p
    def put(p, line):
        p.stdin.write((line + "\n").encode()); p.stdin.flush()
    def got(p):
        try:
            return (p.stdout.read() or b"").decode()
        except (TypeError, OSError):
            return ""
    def status():
        r = subprocess.run([sys.executable, PH, "clipsync", "--json"], env=env, capture_output=True, text=True)
        return json.loads(r.stdout or "{}")

    a, b = link(), link()
    put(a, "H screen-a"); put(b, "H screen-b")
    need("both screens linked", until(lambda: len(status().get("screens", [])) == 2, 10))
    need("named", sorted(s["name"] for s in status()["screens"]) == ["screen-a", "screen-b"])
    need("from: local without ssh", all(s["from"] == "local" for s in status()["screens"]))
    put(a, "C " + b64("hello from a"))
    seen = []
    need("b gets a's clip", until(lambda: seen.append(got(b)) or ("C " + b64("hello from a")) in "".join(seen), 5))
    time.sleep(0.5)
    need("a gets no echo of its own", got(a) == "")
    put(b, "C " + b64("hello from a"))        # the same clip again: it already is on every screen
    time.sleep(0.5)
    need("a repeated clip goes once", got(a) == "")
    put(a, "C " + b64("x" * 2000))            # over max_kb = 1
    put(a, "C " + b64("small"))
    time.sleep(0.5)
    rest = got(b)
    need("over the cap: dropped", b64("x" * 2000) not in rest)
    need("under it, after it: relayed", ("C " + b64("small")) in rest)
    put(a, "C not*base64")
    time.sleep(0.3)
    need("garbage: dropped, link alive", a.poll() is None and got(b) == "")
    for p in (a, b):
        p.stdin.close(); p.wait(5)
    need("a link ends with its screen", a.returncode == 0 and b.returncode == 0)

    profile(False)
    r = subprocess.run([sys.executable, PH, "clipsync"], env=env, input=b"", capture_output=True, timeout=10)
    need("sync off: the link says so", r.stdout == b"X off\n")
    r = subprocess.run([sys.executable, PH, "clipsync", "--script"], env=env, capture_output=True, timeout=10)
    need("sync off: no watcher", r.stdout == b"")
    profile(True)

    # ── two fake screens, the real watcher ────────────────────────────────
    fake = os.path.join(tmp, "bin")
    os.makedirs(fake)
    with open(os.path.join(fake, "xclip"), "w") as f:
        f.write('#!/bin/sh\n'
                'case "$*" in\n'
                '  *"-t TARGETS"*) cat "$CLIPDIR/targets" 2>/dev/null ;;\n'
                '  *-o*) [ -s "$CLIPDIR/clip" ] || exit 1; cat "$CLIPDIR/clip" ;;\n'
                '  *-i*) cat > "$CLIPDIR/new" && mv "$CLIPDIR/new" "$CLIPDIR/clip"; echo x >> "$CLIPDIR/writes" ;;\n'
                'esac\n')
    os.chmod(os.path.join(fake, "xclip"), 0o755)
    watcher = subprocess.run([sys.executable, PH, "clipsync", "--script"], env=env,
                             capture_output=True, text=True).stdout
    need("sync on: a watcher", "MAX=1024" in watcher)
    deck = subprocess.Popen(["sleep", "600"])         # stands in for each screen's `deck`
    procs.append(deck)
    screens = {}
    for n in ("a", "b"):
        d = os.path.join(tmp, "clip-" + n)
        os.makedirs(d)
        with open(os.path.join(d, "clip"), "w") as f:
            f.write("before " + n)                    # what each had before it linked
        e = dict(env, DISPLAY=":fake", CLIPDIR=d, PATH=fake + os.pathsep + env["PATH"])
        w = subprocess.Popen(["sh", "-c", watcher, "clipsync", str(deck.pid), sys.executable, PH, "clipsync"],
                             env=e, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(w)
        screens[n] = (d, w)
    clip = lambda n: open(os.path.join(screens[n][0], "clip")).read()
    def copy(n, text, secret=False):
        d = screens[n][0]
        with open(os.path.join(d, "targets"), "w") as f:
            f.write("UTF8_STRING\n" + ("x-kde-passwordManagerHint\n" if secret else ""))
        with open(os.path.join(d, "new"), "w") as f:
            f.write(text)
        os.rename(os.path.join(d, "new"), os.path.join(d, "clip"))
    def writes(n):
        try:
            return len(open(os.path.join(screens[n][0], "writes")).read().split())
        except OSError:
            return 0

    need("watchers linked", until(lambda: len(status().get("screens", [])) == 2, 10))
    r = subprocess.run([sys.executable, PH, "doctor"], env=env, capture_output=True, text=True, timeout=60)
    need("doctor counts them", "on · 2 screens linked" in r.stdout)
    import screens as screensmod
    pn = screensmod.Panel({"clipboard": {"sync": True}})
    pn.clips = {"local"}
    need("SCREENS marks a linked one clip", pn.link({"from": "local"}) == "clip" and pn.link({"from": "192.0.2.7"}) == "")
    time.sleep(1.5)
    need("nothing from before linking", clip("a") == "before a" and clip("b") == "before b")
    copy("a", "copied on a\nsecond line")
    need("copy on a, paste on b", until(lambda: clip("b") == "copied on a\nsecond line", 6))
    time.sleep(2.5)
    need("no echo back to a", writes("a") == 0 and writes("b") == 1)
    copy("b", "and back from b")
    need("copy on b, paste on a", until(lambda: clip("a") == "and back from b", 6))
    copy("a", "hunter2", secret=True)
    time.sleep(3)
    need("a password manager's clip stays put", clip("b") == "and back from b")
    copy("a", "y" * 1500)
    time.sleep(3)
    need("over the cap: stays put", clip("b") == "and back from b")

    # ── phones: Termux, its API app there or not ──────────────────────────
    # a stand-in for /data/data/com.termux; termux-clipboard-* wait forever
    # for a Termux:API app that isn't installed
    troot = os.path.join(tmp, "termux")
    os.makedirs(troot)
    twatcher = watcher.replace("/data/data/com.termux", troot)
    phones = {}
    for n, tools in (("noapp", {"termux-clipboard-get": "sleep 600", "termux-clipboard-set": "sleep 600"}),
                     ("nopkg", {}),
                     ("ok", {"termux-clipboard-get": "exit 0",
                             "termux-clipboard-set": '[ -e "$CLIPDIR/hang" ] && { rm "$CLIPDIR/hang"; sleep 600; }\n'
                                                     'cat > "$CLIPDIR/new" && mv "$CLIPDIR/new" "$CLIPDIR/clip"'})):
        d = os.path.join(tmp, "phone-" + n)
        os.makedirs(os.path.join(d, "bin"))
        for t, body in tools.items():
            with open(os.path.join(d, "bin", t), "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(os.path.join(d, "bin", t), 0o755)
        e = dict(env, CLIPDIR=d, PATH=os.path.join(d, "bin") + os.pathsep + env["PATH"])
        w = subprocess.Popen(["sh", "-c", twatcher, "clipsync", str(deck.pid), sys.executable, PH, "clipsync"],
                             env=e, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(w)
        phones[n] = d
    pclip = lambda n: (open(os.path.join(phones[n], "clip")).read()
                       if os.path.exists(os.path.join(phones[n], "clip")) else "")
    why = lambda: sorted(x.get("nopaste", "") for x in status().get("screens", []))
    need("phones linked, each saying what it lacks (%s)" % why(),
         until(lambda: why() == ["", "", "", "pkg install termux-api", "the Termux:API app"], 15))
    r = subprocess.run([sys.executable, PH, "doctor"], env=env, capture_output=True, text=True, timeout=60)
    need("doctor says what a phone that can't paste needs",
         "needs the Termux:API app" in r.stdout and "needs pkg install termux-api" in r.stdout)
    pn.nopaste = {"local": "the Termux:API app"}
    need("SCREENS marks one that can't paste clip?", pn.link({"from": "local"}) == "clip?")
    copy("a", "to the phones")
    need("a phone with Termux:API pastes", until(lambda: pclip("ok") == "to the phones", 6))
    open(os.path.join(phones["ok"], "hang"), "w").close()
    copy("a", "this one hangs")
    time.sleep(1)
    copy("a", "and this one lands")
    need("a paste that hangs doesn't hold up the next", until(lambda: pclip("ok") == "and this one lands", 20))

    deck.kill(); deck.wait()
    need("watchers end with their deck",
         until(lambda: all(w.poll() is not None for _, w in screens.values()), 8))
    need("phone watchers end with their deck too",
         until(lambda: all(p.poll() is not None for p in procs if p.args[0] == "sh"), 15))
    need("the hub goes after the last screen",
         until(lambda: not os.path.exists(os.path.join(env["XDG_RUNTIME_DIR"], "phosphor-clip.sock")), 20))

    # ── every generated deck script still parses ──────────────────────────
    import clipsync, gen, phone
    v = {"brain": "nimbus", "target": "you@nimbus", "session": "deck", "command": "deck",
         "clip": clipsync.launch("you@nimbus", "~/.local/bin/phosphor")}
    texts = {"connect ssh": gen.CONNECT % dict(v, body=gen.CONNECT_SSH % v),
             "connect mosh": gen.CONNECT % dict(v, body=gen.CONNECT_MOSH % v),
             "attach": gen.ATTACH % {"phosphor": "/opt/phosphor", "session": "deck",
                                     "clip": clipsync.launch_local("/opt/phosphor")},
             "phone kit": phone.script({}), "screen kit": phone.screen_script({})}
    for name, t in texts.items():
        r = subprocess.run(["sh", "-n"], input=t, text=True, capture_output=True)
        need("%s parses (%s)" % (name, r.stderr.strip()), r.returncode == 0)
        need("%s starts the watcher" % name, "clipsync --script" in t)
    r = subprocess.run(["sh", "-n", "-c", clipsync.WATCHER], capture_output=True, text=True)
    need("the watcher parses (%s)" % r.stderr.strip(), r.returncode == 0)
finally:
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM) if p.args[0] == "sh" else p.kill()
            except OSError:
                pass
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print("clipsync-check FAIL:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("clipsync-check ok")
