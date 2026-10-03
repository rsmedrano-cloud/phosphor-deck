#!/usr/bin/env python3
"""Text from outside the brain never reaches a screen as escape sequences.

A fleet host's poll answer (either poller), a container's logs through
`phosphor tail`, a chat notification, an event line, a broadcast's output,
CI and review data: each is fed something hostile here (an OSC 52 that
would write every screen's clipboard, a screen clear, a retitle, a C1 CSI,
a bidi override) and what comes out the other side must hold none of it,
while plain colors in logs and the text itself survive.

    python3 tests/sanitize-check.py
"""
import io, json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def need(what, ok):
    if not ok: fails.append(what)

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["PHOSPHOR_CACHE"] = os.path.join(home, "cache")
os.environ["PHOSPHOR_DATA"] = os.path.join(home, "data")
os.environ["PHOSPHOR_PROFILE"] = os.path.join(home, "deck.toml")
os.makedirs(os.environ["PHOSPHOR_CACHE"]); os.makedirs(os.environ["PHOSPHOR_DATA"])

BIDI = chr(0x202e)
EVIL = ("\x1b]52;c;cm0gLXJmIH4=\x07" "\x1b[2J" "\x1b]0;pwned\x1b\\" "\x9b31m" "\x1bc" + BIDI
        + "\x1bP+q\x1b\\" "\x08\x7f")
def dirty(s):
    return any(x in s for x in ("\x1b]", "\x07", "\x1b[2J", "\x9b", "\x1bc", BIDI, "\x1bP", "\x08", "\x7f"))

from sanitize import clean, clean_text, clean_tree, pipe

# ── the functions themselves ──────────────────────────────────
need("clean: keeps the text", clean("gpu" + EVIL + " ok") == "gpu ok")
need("clean: newline and tab become spaces", clean("a\nb\tc") == "a b c")
need("clean: lines=True keeps newlines", clean("a\nb" + EVIL, lines=True) == "a\nb")
need("clean: non-strings pass", clean(3) == 3 and clean(None) is None)
t = clean_text("a\x1b[31mred\x1b[0m" + EVIL + " b\r\nc\rd\x1b[Ae\n")
need("clean_text: keeps SGR colors", "\x1b[31mred\x1b[0m" in t)
need("clean_text: keeps CRLF, drops a lone CR", "b\r\nc" in t and "c\rd" not in t)
need("clean_text: drops cursor moves", "\x1b[A" not in t)
need("clean_text: nothing dirty left: %r" % t, not dirty(t))
need("clean_text: a colon SGR (truecolor) stays", "\x1b[38:2:1:2:3m" in clean_text("\x1b[38:2:1:2:3mx"))
tr = clean_tree({"k" + EVIL: ["x" + EVIL, ("y", 1)], "n": 2})
need("clean_tree: keys, lists, tuples: %r" % tr, tr == {"k": ["x", ("y", 1)], "n": 2})
need("clean: an unterminated OSC eats to the end", clean("a\x1b]52;c;abc") == "a")

# the stream filter: output cleaned, the command's own exit status back (255: ssh's link)
out = io.BytesIO()
rc = pipe(["sh", "-c", "printf 'hi\\033]52;c;eA==\\007 there\\r\\n'; printf 'x\\033[2Jy\\n' >&2; exit 255"], out)
o = out.getvalue().decode()
need("pipe: exit status passes through (got %r)" % rc, rc == 255)
need("pipe: text and stderr arrive, escapes don't: %r" % o, "hi there\r\n" in o and "xy\n" in o and not dirty(o))
out = io.BytesIO()
need("pipe: a missing program says so", pipe(["/nonexistent/prog"], out) == 127 and b"nonexistent" in out.getvalue())

# ── fleet: the Python poller's own answer ─────────────────────
import fleet
script = os.path.join(home, "collect.sh")
open(script, "w").write("printf 'CPU=5\\nMEMU=1\\nMEMT=2\\n'\n"
                        "printf 'OS=Debian\\033]52;c;eA==\\007 12\\n'\n"
                        "printf 'GPU=gp\\033[2Ju|1|2|3|4\\n'\n"
                        "printf 'MNT=/\\033]0;t\\007|5|1G\\n'\n"
                        "printf 'CTR=dock\\033cer|1|0\\n'\n")
fleet.COLLECT = script
d = fleet.collect("here", None)
need("fleet.collect: answered: %r" % d, d.get("ok") and d.get("CPU") == 5)
need("fleet.collect: OS is text: %r" % d.get("OS"), d.get("OS") == "Debian 12")
need("fleet.collect: GPU, mounts, containers: %r" % d,
     d["gpu"][0]["name"] == "gpu" and d["mnt"][0][0] == "/" and d["ctr"][0] == "docker")
open(script, "w").write("printf 'boom\\033]52;c;eA==\\007' >&2\n")
d = fleet.collect("here", None)
need("fleet.collect: an error from the host is text too: %r" % d, not d["ok"] and not dirty(d["err"]))

# ── fleet.json, as either poller (the Rust one too) may write it ──
host = "nova" + EVIL
json.dump({"t": 9999999999, "hosts": {
    host: {"ok": False, "err": "refused" + EVIL},
    "atlas": {"ok": True, "CPU": 5, "MEMU": 50, "MEMT": 1000, "mnt": [["/" + EVIL, 99, "1G"]],
              "OS": "Arch" + EVIL, "gpu": [{"name": "rtx" + EVIL}]},
}}, open(os.path.join(os.environ["PHOSPHOR_CACHE"], "fleet.json"), "w"))
st = fleet.read_state()
need("fleet.read_state: clean: %r" % st, "nova" in st and not dirty(json.dumps(st, ensure_ascii=False)))
import glance
g = "\n".join(glance.frame(80, 40))
need("glance: shows the host, no escapes", "nova" in g and not dirty(g))
import pulse
need("pulse: its reason is text", not dirty(repr(pulse.read_state())))
import adjutant
need("adjutant: fleet.json is text", not dirty(json.dumps(adjutant._read_fleet(), ensure_ascii=False)))

# ── events anyone appends to ──────────────────────────────────
open(adjutant.EVENTS, "w").write("SYS" + EVIL + "\tdisk full" + EVIL + "\n")
ev, _ = adjutant.read_events(0)
need("adjutant: an event line is text: %r" % ev, ev == [("SYS", "disk full")])

# ── a chat notification ───────────────────────────────────────
import mentions
mentions.push_it = lambda e: None
open(mentions.EVENTS, "w").close()     # the adjutant check above left a dirty line there
sys.stdin = io.StringIO(json.dumps({"from": "sam" + EVIL, "message": "hey" + EVIL + " you", "mention": True}))
mentions.hook()
sys.stdin = sys.__stdin__
feed = open(mentions.FEED).read()
need("mention-hook: the feed is text: %r" % feed, "sam" in feed and "hey you" in feed and "\\u001b" not in feed and not dirty(feed))
need("mention-hook: the event line is text", not dirty(open(mentions.EVENTS).read()))
open(mentions.FEED, "a").write(json.dumps({"t": 2.0, "from": "old" + EVIL, "message": "x" + EVIL}) + "\n")
need("mentions: an older entry is cleaned on reading", not dirty(json.dumps(mentions.entries(), ensure_ascii=False)))

# ── broadcast's output ────────────────────────────────────────
import broadcast
_, rc, out, _ = broadcast.run_one({"name": "here", "local": True},
                                  "printf 'up\\033]52;c;eA==\\007 \\033[32mok\\033[0m\\n'", 10)
need("broadcast: output is text, colors stay: %r" % out, rc == 0 and "up \x1b[32mok\x1b[0m" == out)

# ── phosphor tail: through the filter, ssh's 255 kept for --reconnect ──
import tail, deckconf
deckconf.load = lambda *a, **k: ({"hosts": [{"name": "nimbus", "ssh": "nimbus"}]}, None)
seen = []
def fake_exec(path, argv):
    seen.append(argv); raise SystemExit(0)
tail.os.execv = fake_exec
for args in (["nimbus"], ["nimbus", "docker/web"]):
    sys.argv = ["tail"] + args
    try: tail.main()
    except SystemExit: pass
need("tail: both runs exec'd", len(seen) == 2)
for argv in seen:
    i = argv.index("--reconnect")
    rest = argv[i + 2:]
    need("tail: the command goes through sanitize.py: %r" % argv,
         rest[1:3] == [getattr(tail, "SANITIZE", None), "--"] and rest[3] == "ssh")
need("tail: docker logs still asked for", "docker" in seen[1])

# ── CI and review: every answer parsed is cleaned ─────────────
for f in ("ci.py", "review.py"):
    src = open(os.path.join(ROOT, "lib", f)).read()
    loads = len(re.findall(r"json\.loads\(", src))
    wrapped = len(re.findall(r"clean_tree\(json\.loads\(", src))
    need("%s: every json.loads is cleaned (%d of %d)" % (f, wrapped, loads), loads and loads == wrapped)

if fails:
    print("FAIL: sanitize"); [print("  - " + f) for f in fails]; sys.exit(1)
print("ok: sanitize")
