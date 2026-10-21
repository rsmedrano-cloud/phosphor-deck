#!/usr/bin/env python3
"""While you were away (lib/away.py): coming in, one screen with what
happened since you last left; nothing at all when nothing did. Also the
events file's time per line (lib/events.py), which it reads: written by
notify, read by the adjutant in either format. Nothing real is touched: a
temp HOME, fake fleet.json, CI answer, chat feed and notebook; the screen
itself runs in a pty.

    python3 tests/away-check.py
"""
import json, os, pty, re, select, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
for v in ("PHOSPHOR_DATA", "PHOSPHOR_CACHE", "PHOSPHOR_NOTES", "ZELLIJ"):
    os.environ.pop(v, None)
home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["USER"] = "me"
os.makedirs(os.path.join(home, ".cache/phosphor"))
os.makedirs(os.path.join(home, ".local/share/phosphor"))
prof = os.path.join(home, "deck.toml")
open(prof, "w").write('[deck]\nsession = "probe"\n')
os.environ["PHOSPHOR_PROFILE"] = prof

fails = []
def need(what, ok):
    if not ok: fails.append(what)
def strip(s):
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)

import away, events, adjutant, glance, notes, snooze

# ── the events file ──────────────────────────────────────────
now = time.time()
open(events.path(), "w").write("SYS\tfrom before, no time\n")
subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "notify", "--no-push", "--no-tts",
                "--tab", "SYS", "db-box\tis\nunreachable"], capture_output=True, timeout=30)
last = open(events.path()).read().splitlines()[-1]
tab, text, t = events.parse(last)
need("notify writes the time last, the text flattened to one line",
     tab == "SYS" and text == "db-box is unreachable" and t and abs(t - now) < 60)
need("an old line parses, no time", events.parse("SYS\tdisk full") == ("SYS", "disk full", None))
need("a text with a tab of its own but no time stays whole",
     events.parse("SYS\ta\tb") == ("SYS", "a\tb", None))
pos = 0
got, pos = adjutant.read_events(0)
need("the adjutant reads both formats, the time never in the text",
     got == [("SYS", "from before, no time"), ("SYS", "db-box is unreachable")])
need("since() skips lines with no time", [x[2] for x in events.since(0)] == ["db-box is unreachable"])

# ── what the screen collects ─────────────────────────────────
def poll(**hosts):
    json.dump({"t": time.time(), "hosts": hosts}, open(glance.CACHE, "w"))
def ci(status, sha):
    json.dump({"pipelines": [{"name": "app", "sha": sha, "status": status, "commit": "fix it"}]},
              open(os.path.join(home, ".cache/phosphor/answer-ci.json"), "w"))
ok = {"ok": True, "mnt": [["/", 40, "x"]]}
full = {"ok": True, "mnt": [["/", 97, "x"]]}

open(events.path(), "w").close()
poll(vault=full, relay=ok)
ci("SUCCESS", "aaaa")
away.saw(now - 7200)
seen = away.load()
need("seen.json keeps the time, the problems, the pipelines",
     seen["t"] == now - 7200 and "vault disk" in seen["problems"] and seen["ci"]["app"][1] == "SUCCESS")
need("nothing happened: nothing to show", away.sections(seen, now) == [])

events.append("SYS", "relay is unreachable", now - 3000)
events.append("SYS", "relay is back", now - 2000)
events.append("SYS", "nimbus is unreachable (snoozed)", now - 1900)
events.append("COMMS", "@alice: hi", now - 1500)       # the chat feed says it, not this line
events.append("", "work notes ready: @alice", now - 100)
events.append("SYS", "before you left", now - 8000)
poll(vault=ok, relay={"ok": False, "err": "timeout"})
ci("FAILED", "bbbb")
with open(os.path.join(home, ".local/share/phosphor/mentions.jsonl"), "w") as f:
    f.write(json.dumps({"t": now - 1500, "from": "alice", "message": "hi", "mention": True}) + "\n")
    f.write(json.dumps({"t": now - 9000, "from": "bob", "message": "old", "mention": True}) + "\n")
notes.append(notes.PATH, "note", "claude", "2.4.7 on dev")
notes.append(notes.PATH, "note", "me", "my own note")
json.dump({"behind": 3, "latest": "2.5.0"}, open(os.path.join(home, ".cache/phosphor/update.json"), "w"))

secs = dict(away.sections(seen, now))
fl = [t for _, t in secs.get("FLEET", [])]
need("fleet: the alerts in order, not the snoozed one or one from before",
     fl[:2] == ["relay is unreachable", "relay is back"] and not any("nimbus" in x or "before" in x for x in fl))
need("fleet: what's wrong now and wasn't, what was and isn't",
     ("now", "relay: down, timeout") in secs["FLEET"] and ("gone", "vault: disk 97%") in secs["FLEET"])
need("pipelines: a finished run you hadn't seen", secs.get("PIPELINES") == [("FAILED", "app  bbbb fix it")])
need("chat: from the feed, since you left", [t for _, t in secs.get("CHAT", [])] == ["@alice: hi"])
need("notifications: the rest, chat and fleet lines left out",
     [t for _, t in secs.get("NOTIFICATIONS", [])] == ["work notes ready: @alice"])
need("notebook: what others wrote, not yours", secs.get("NOTEBOOK") == [("claude", "note: 2.4.7 on dev")])
need("phosphor: a newer one", "2.5.0" in secs.get("PHOSPHOR", [("", "")])[0][1])

snooze.snooze("relay", ["down"])
need("snoozed now: not in what's wrong", ("now", "relay: down, timeout") not in dict(away.sections(seen, now))["FLEET"])
os.remove(snooze.path())

lines = away.frame(seen, away.sections(seen, now), 40, 12, now)
need("the frame fits the screen: rows and columns",
     len(lines) <= 12 and all(len(strip(l)) <= 40 for l in lines) and "any key" in strip(lines[-1]))
many = [("FLEET", [("12:00", "line %d" % i) for i in range(9)])]
txt = strip("\n".join(away.frame(seen, many, 80, 40, now)))
need("a long section: the latest few, and how many before", "+%d before these" % (9 - away.PER) in txt
     and "line 8" in txt and "line 0" not in txt)

# FLEET not running now: the last known problems stay for next time
os.remove(glance.CACHE)
away.saw(now)
need("fleet not running: saw() keeps what it knew", "vault disk" in away.load()["problems"])
need("the mark moved: nothing new since", away.sections(away.load(), now + 1) == [])

# ── the screen in a pty: any key closes it, then you're here ─
away.saw(now - 7200)
events.append("SYS", "relay is unreachable", now - 60)
def run(profile_text):
    open(prof, "w").write(profile_text)
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["COLUMNS"], os.environ["LINES"] = "80", "24"
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import away as a, deckconf
        a.show(deckconf.load()[0])
        os._exit(0)
    buf, end = b"", time.time() + 20
    while time.time() < end and b"any key" not in buf:
        if select.select([fd], [], [], 0.5)[0]:
            try: buf += os.read(fd, 4096)
            except OSError: break
        elif os.waitpid(pid, os.WNOHANG)[0]:
            break
    shown = b"WHILE YOU WERE AWAY" in buf
    if shown:
        time.sleep(0.3)
        os.write(fd, b"x")
    t0 = time.time()
    while time.time() - t0 < 10 and not os.waitpid(pid, os.WNOHANG)[0]:
        try:
            if select.select([fd], [], [], 0.2)[0]: os.read(fd, 4096)
        except OSError: pass
    os.close(fd)
    return shown, time.time() - t0 < 10
shown, done = run('[deck]\nsession = "probe"\n')
need("in a terminal it shows, and a key closes it", shown and done)
need("closing it moves the mark", away.load()["t"] > now - 60)
away.saw(now - 7200)
shown, done = run('[deck]\nsession = "probe"\naway = false\n')
need("away = false: never shown", not shown and done)

if fails:
    print("FAIL away-check:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok away-check")
