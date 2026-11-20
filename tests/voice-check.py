#!/usr/bin/env python3
"""Voice in (#85): a screen records, the brain writes it down, the text
lands in the pane without Enter.

    python3 tests/voice-check.py

No microphone and no whisper: a fake termux-microphone-record, ffmpeg and
whisper-cli. First the parts: whisper's lines cleaned, when voice is on,
the screen's script beside the clipboard's, the Alt-m bind, the bar's MIC
only while voice is on. Then the screen's real half (voice.WATCHER, in a
pretend Termux) linked through `phosphor clipsync voice` to the hub: it
says it can record, records when asked, sends the file on stop, forgets it
when the asker goes; one without termux-api says what it needs.
Then a real zellij (zjprobe): a tap on MIC over a shell, Enter, and the
words are typed at that shell's prompt, not run. Needs zellij for that
part; without it, it says so and checks the rest.
"""
import json, os, shutil, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

home = tempfile.mkdtemp(prefix="voicecheck-")
bindir = os.path.join(home, ".local/bin")
for d in (bindir, "run", ".config/phosphor", "termux"):
    os.makedirs(os.path.join(home, d), exist_ok=True)
os.chmod(os.path.join(home, "run"), 0o700)
log = os.path.join(home, "mic.log")

def fake(name, body):
    p = os.path.join(bindir, name)
    open(p, "w").write("#!/bin/sh\n" + body)
    os.chmod(p, 0o755)
    return p

# the recorder: -f FILE starts (the file gets the "audio"), -q stops, -i answers
fake("termux-microphone-record", 'echo "$@" >> %s\n'
     'while [ $# -gt 0 ]; do case $1 in -f) shift; printf FAKEAUDIO > "$1";; esac; shift; done\n' % log)
fake("ffmpeg", 'for a; do last=$a; done\ncp "$(echo "$@" | sed "s/.* -i \\([^ ]*\\) .*/\\1/")" "$last"\n')
whisper = fake("whisper-cli", 'printf " hola deck\\n [BLANK_AUDIO]\\n (music)\\n"\n')
model = os.path.join(home, "ggml-test.bin")
open(model, "w").write("x")
PROFILE = '[voice]\nenabled = true\nwhisper = "%s"\nmodel = "%s"\n' % (whisper, model)
open(os.path.join(home, ".config/phosphor/deck.toml"), "w").write(PROFILE)
env = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
env.update(HOME=home, XDG_RUNTIME_DIR=os.path.join(home, "run"), XDG_CACHE_HOME=os.path.join(home, ".cache"),
           PHOSPHOR_PROFILE=os.path.join(home, ".config/phosphor/deck.toml"),
           PHOSPHOR_DATA=os.path.join(home, "data"), PHOSPHOR_CACHE=os.path.join(home, ".cache/phosphor"),
           PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
os.environ.clear(); os.environ.update(env)

import voice, clipsync, shortcuts, bar, deckconf

# ── the parts ─────────────────────────────────────────────────
need("whisper's lines: one line, no [BLANK_AUDIO] or (sounds)",
     voice.clean(" hola deck\n [BLANK_AUDIO]\n (music) y más\n") == "hola deck y más")
prof = deckconf.load()[0]
need("[voice] enabled with whisper and a model: on, nothing missing (%r)" % voice.missing(prof),
     voice.on(prof) and voice.missing(prof) == [])
need("[voice] enabled = false: off", not voice.on({"voice": {"enabled": False}}))
need("unset, and no whisper here: off", not voice.on({"voice": {"whisper": "/nonexistent"}}))
need("no whisper: what's missing says how to get it (doctor and MIC show it)",
     any("phosphor voice install" in m for m in voice.missing({"voice": {"whisper": "/nonexistent"}})))
text, why = voice.transcribe(model, prof)
need("transcribe through ffmpeg and whisper (%r, %r)" % (text, why), text == "hola deck" and why is None)

off = {"clipboard": {"sync": False}, "voice": {"enabled": False}}
need("neither clipboard nor voice: no script for the screen", clipsync.script(off) == "")
clip_only = clipsync.script({"clipboard": {"sync": True}, "voice": {"enabled": False}})
need("clipboard only: its watcher as it was", clip_only == clipsync.WATCHER.replace("@MAX@", str(clipsync.cap({}))))
mic_only = clipsync.script({"voice": {"enabled": True}})
need("voice only: the microphone's watcher", mic_only == voice.WATCHER)
both = clipsync.script({"clipboard": {"sync": True}, "voice": {"enabled": True}})
need("both: side by side, then wait", both.count(") &\n") == 2 and both.endswith("wait\n"))
for name, s in (("voice", mic_only), ("both", both)):
    need("%s: sh -n passes" % name, subprocess.run(["sh", "-n", "-c", s]).returncode == 0)

kdl = shortcuts.block({})
need("Alt m runs voice --here in place, named MIC", 'bind "Alt m"' in kdl and "voice --here" in kdl and 'name "MIC"' in kdl)
need("the bar: MIC after HOME while voice is on", [k[0] for k in bar.keys_shown(prof)][:2] == ["home", "mic"])
need("the bar: no MIC while it's off", "mic" not in [k[0] for k in bar.keys_shown(off)])
need("a tap on MIC opens voice --here in place", bar.IN_PLACE["mic"] == ("MIC", ["voice", "--here"]))

# ── the screen's half, linked to the hub ──────────────────────
PHOS = os.path.join(ROOT, "phosphor")
termux = os.path.join(home, "termux")
script = voice.WATCHER.replace("/data/data/com.termux", termux)
deck = subprocess.Popen(["sleep", "300"])               # the deck the watcher lives beside
watcher = subprocess.Popen(["sh", "-c", script, "voice", str(deck.pid), sys.executable, PHOS, "clipsync"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=True)

def wait(cond, t=10):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False

def mic_screens():
    return [s for s in voice.linked() if s.get("mic")]

try:
    need("the screen links and says it can record", wait(lambda: mic_screens(), 15))
    scr = (mic_screens() or [{}])[0]
    s = voice.connect()
    a = voice.Asker(s)
    a.say("R %s 30" % scr.get("id"))
    need("asked, it records (%r)" % (open(log).read() if os.path.exists(log) else ""),
         wait(lambda: os.path.exists(log) and "-f " in open(log).read() and "-l 30" in open(log).read()))
    a.say("S")
    got = a.line(10)
    need("stopped, it sends the recording (%r)" % (got or "")[:40], got == "A RkFLRUFVRElP")   # FAKEAUDIO
    s.close()

    open(log, "w").close()
    s = voice.connect()
    a = voice.Asker(s)
    a.say("R %s 30" % scr.get("id"))
    wait(lambda: "-f " in open(log).read())
    s.close()                                            # MIC went (Esc, or its pane closed)
    need("the asker gone, the recording is forgotten", wait(lambda: "-q" in open(log).read().split("-f ")[-1]))

    os.remove(os.path.join(bindir, "termux-microphone-record"))
    os.kill(deck.pid, signal.SIGTERM); deck.wait()
    watcher.wait(timeout=15)
    deck = subprocess.Popen(["sleep", "300"])
    watcher = subprocess.Popen(["sh", "-c", script, "voice", str(deck.pid), sys.executable, PHOS, "clipsync"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    need("without termux-api: linked, and it says what it needs (%r)" % voice.linked(),
         wait(lambda: any(not x["mic"] and x.get("why") == "pkg install termux-api" for x in voice.linked()), 15))
finally:
    for p in (deck,):
        p.kill(); p.wait()
    try:
        watcher.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(watcher.pid, signal.SIGKILL)
fake("termux-microphone-record", 'echo "$@" >> %s\n'
     'while [ $# -gt 0 ]; do case $1 in -f) shift; printf FAKEAUDIO > "$1";; esac; shift; done\n' % log)

# ── a real zellij: a tap on MIC, Enter, the words at the prompt ─
import zjprobe
if not zjprobe.zellij():
    print("  zellij isn't installed: the parts and the link only")
else:
    PROBE = '''
[deck]
session = "voicecheck"

[bar]
enabled = true

[voice]
enabled = true
whisper = "%s"
model = "%s"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "ONE"
panes = [ { cmd = "" } ]
''' % (whisper, model)
    with zjprobe.Probe(PROBE, session="voicecheck", cols=100, rows=30) as z:
        for f in ("termux-microphone-record", "ffmpeg", "whisper-cli"):
            shutil.copy2(os.path.join(bindir, f), os.path.join(z.home, ".local/bin", f))
        zt = os.path.join(z.home, "termux"); os.makedirs(zt, exist_ok=True)
        zdeck = subprocess.Popen(["sleep", "300"])
        zw = subprocess.Popen(["sh", "-c", voice.WATCHER.replace("/data/data/com.termux", zt), "voice",
                               str(zdeck.pid), sys.executable, PHOS, "clipsync"], env=z.env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
        try:
            need("the deck came up", z.wait(lambda: z.tabs()[:1] == ["ONE"], 20))
            shell = lambda: next((p for p in json.loads(z.action("list-panes", "-a", "-j") or "[]")
                                  if not p["is_plugin"] and not bar.is_bar(p)), None)
            z.keys("echo MAR''KER-$((6*7))\r", 1.0)
            need("the shell shows the marker", z.wait(lambda: any("MARKER-42" in r for r in z.screen()), 15))

            def bar_rows():
                b = next((p for p in json.loads(z.action("list-panes", "-a", "-j") or "[]") if bar.is_bar(p)), None)
                if not b:
                    return b, ["", ""]
                out = os.path.join(z.home, "bar.txt")
                z.action("dump-screen", "--pane-id", "terminal_%d" % b["id"], "--path", out)
                try:
                    return b, (open(out).read().splitlines() + ["", ""])[:2]
                except OSError:
                    return b, ["", ""]
            need("MIC is on the bar (%r)" % bar_rows()[1], z.wait(lambda: " MIC " in bar_rows()[1][1], 15))
            need("the probe's screen linked", z.wait(lambda: subprocess.run(
                [sys.executable, PHOS, "voice", "--json"], env=z.env, capture_output=True, text=True).stdout.count('"mic": true') == 1, 15))
            b, rows = bar_rows()
            col = rows[1].find("MIC")
            x, y = b["pane_content_x"] + col + 2, b["pane_content_y"] + 2
            z.keys(b"\x1b[<0;%d;%dM" % (x, y), 0.1)
            z.keys(b"\x1b[<0;%d;%dm" % (x, y), 0.8)
            need("a tap on MIC: recording on the screen", z.wait(lambda: any("recording on" in r for r in z.screen()), 15))
            need("MIC says how to get back to the shell (#110)", any("Esc: back to" in r for r in z.screen()))
            z.wait(lambda: zjprobe.reading_keys(z, "--here"), 10)
            z.keys("\r", 0.5)
            need("Enter: the words are typed at the shell's prompt (%r)" % z.screen()[-3:],
                 z.wait(lambda: any(r.rstrip().endswith("hola deck") for r in z.screen()), 20))
            z.keys(b"\x15", 0.3)       # Ctrl-U: never run it
            need("not run: no Enter after it", not any("hola: command not found" in r or "hola: not found" in r
                                                       for r in z.screen()))
        finally:
            zdeck.kill(); zdeck.wait()
            try:
                zw.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(zw.pid, signal.SIGKILL)

shutil.rmtree(home, ignore_errors=True)
if fails:
    print("voice-check FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("voice-check ok")
