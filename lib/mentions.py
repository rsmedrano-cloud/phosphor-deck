"""phosphor mentions - a read-only feed of chat notifications.

`phosphor mention-hook` reads one notification as JSON on stdin,
{"from", "message", "mention"}, and only writes it down. Anything can feed
it: a bot, a script, a CI job, a chat client's hook. `--setup` wires
matterhorn's activityNotifyCommand to it, which runs for every post your
Mattermost notification preferences allow (usually mentions and DMs).
Nothing in here ever sends anything back to the chat, not even a canned
reply: answering is yours.

While something is unseen the chat tab reads "COMMS ●2"; tapping the tab
takes you there and arriving there clears it. The SYS adjutant shows who
wrote and what -- and it reaches you off the deck too, the same way
`phosphor notify` does: pushed to your phone if [push] is on, spoken if
[tts] is on.

    phosphor mentions            the feed, newest first (tap: go to the chat)
    phosphor mentions --setup    point matterhorn at the hook

With `prepare` in the profile's [mentions], "prepare notes" on a notification
runs that command with a briefing prompt on stdin and saves what it prints to
WORK NOTES (phosphor notes --book work). Only when you press it.
"""
import json, os, select, shutil, subprocess, sys, termios, textwrap, time, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey as ui_getkey
import deckconf

HOME   = os.path.expanduser("~")
FEED   = os.path.join(deckconf.data_dir(), "mentions.jsonl")
SEEN   = os.path.join(deckconf.cache_dir(), "mentions.seen")
EVENTS = os.path.join(deckconf.cache_dir(), "events")
HOOK   = os.path.join(HOME, ".local/share/phosphor/mention-hook")
MHCONF = os.path.join(HOME, ".config/matterhorn/config.ini")
APPS   = {"matterhorn", "iamb", "gomuks"}   # chat clients: their tab is the chat tab
CHAT   = "COMMS"                # or a tab with this name, whatever runs in it
KEEP   = 300
MARK   = " ●"
PREP   = os.path.join(deckconf.cache_dir(), "prepare")
WORK   = os.path.join(deckconf.data_dir(), "work.md")
PROMPT = """You are preparing briefing notes for the person who received this chat
notification. Do NOT reply to anyone and do not post or send anything anywhere:
only write notes for them. If the working folder has a GEMINI.md, AGENTS.md,
CLAUDE.md or README, read it first: it describes your role and the docs.
Use the documentation and context available to you.
Be concise: what is being asked, relevant background from the docs, likely next
steps, open questions. Write in the language of the message.

From: {sender}
Message: {message}
"""

def _zj_bin():
    p = os.path.join(HOME, ".local/bin/zellij")
    return p if os.path.exists(p) else (shutil.which("zellij") or "zellij")

def zj(sess, *a):
    try:
        return subprocess.run([_zj_bin(), "-s", sess, "action"] + list(a),
                              capture_output=True, text=True, timeout=8).stdout
    except Exception:
        import dlog
        dlog.event_throttled("MENTIONS", "zj-failed")   # never str(e): it quotes the command, home path included
        return ""

# ── the hook ─────────────────────────────────────────────────
def hook():
    """Called by matterhorn. It must return at once and print NOTHING:
    any output or a non-zero exit shows up as an error in the chat."""
    try:
        d = json.loads(sys.stdin.read() or "{}")
        e = {"t": round(time.time(), 1),
             "from": str(d.get("from", ""))[:64],
             "message": " ".join(str(d.get("message", "")).split())[:500],
             "mention": bool(d.get("mention"))}
        os.makedirs(os.path.dirname(FEED), exist_ok=True)
        fd = os.open(FEED, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if os.path.getsize(FEED) > KEEP * 1200:          # trim now and then
            lines = open(FEED).read().splitlines()[-KEEP:]
            open(FEED, "w").write("\n".join(lines) + "\n")
        os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
        with open(EVENTS, "a") as f:                     # the SYS adjutant
            f.write("COMMS\t@%s: %s\n" % (e["from"], e["message"][:80]))
        push_it(e)
    except Exception:
        import dlog
        dlog.crash("MENTIONS")     # never the payload itself: just the exception
    return 0

def push_it(e):
    """Push+TTS this notification, off a detached process so the hook
    still returns at once (push has a network timeout). The event line
    above is already written, so this goes through `phosphor notify
    --no-event`: push if [push] is on, TTS if [tts] is on, the floating
    toast if notifier is on -- same pipeline as any other notification,
    just without a second event line."""
    try:
        subprocess.Popen([sys.executable, os.path.join(REPO, "phosphor"), "notify", "--tab", CHAT,
                          "--no-event", "@%s: %s" % (e["from"], e["message"])],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ── the feed ─────────────────────────────────────────────────
def entries():
    out = []
    try:
        for l in open(FEED):
            try: out.append(json.loads(l))
            except ValueError: pass
    except OSError:
        pass
    return out

def seen():
    try: return float(open(SEEN).read().strip() or 0)
    except (OSError, ValueError): return 0.0

def mark_seen():
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    open(SEEN, "w").write(str(time.time()))

def unread():
    s = seen()
    return sum(1 for e in entries() if e.get("t", 0) > s)

# ── the tab marker ───────────────────────────────────────────
def chat_tab(sess):
    """(tab id, tab name, {pane ids}) of the tab running the chat app."""
    try:
        panes = json.loads(zj(sess, "list-panes", "-t", "-c", "-j") or "[]")
    except ValueError:
        return None
    named = lambda p: (p.get("tab_name") or "").split(MARK)[0].strip() == CHAT
    for p in sorted(panes, key=lambda p: not named(p)):        # a COMMS tab first
        cmd = (p.get("terminal_command") or "").split()
        if not p.get("is_plugin") and (named(p) or any(os.path.basename(c) in APPS for c in cmd)):
            tid = p["tab_id"]
            ids = {"terminal_%d" % q["id"] for q in panes
                   if q.get("tab_id") == tid and not q.get("is_plugin")}
            return tid, p.get("tab_name", ""), ids, "terminal_%d" % p["id"]
    return None

def mark_once(sess, before):
    """Update the tab name; returns the clients now on the chat tab."""
    tab = chat_tab(sess)
    if not tab:
        return set()
    tid, name, ids, _ = tab
    now_on = set()
    for l in zj(sess, "list-clients").splitlines()[1:]:
        f = l.split()
        if len(f) >= 2 and f[1] in ids:
            now_on.add(f[0])
    if now_on - before:          # someone just arrived at the chat tab
        mark_seen()
    n = unread()
    base = name.split(MARK)[0].rstrip() or "COMMS"
    want = base + ("%s%d" % (MARK, n) if n else "")
    if want != name:
        zj(sess, "rename-tab-by-id", str(tid), want)
    return now_on

def marker(sess):
    """Runs inside fleet, the deck's always-on worker. Also clears any
    generic tab mark `phosphor notify` set (see tabmark.py) -- same loop,
    same cadence, one thread doing both jobs."""
    on = set()
    import tabmark
    while True:
        try: on = mark_once(sess, on)
        except Exception:
            import dlog
            dlog.event_throttled("MENTIONS", "mark-failed")
        try: tabmark.tick(sess)
        except Exception:
            import dlog
            dlog.event_throttled("TABMARK", "tick-failed")
        time.sleep(3)

# ── setup ────────────────────────────────────────────────────
def setup():
    """Write the hook wrapper and point matterhorn's config at it."""
    os.makedirs(os.path.dirname(HOOK), exist_ok=True)
    open(HOOK, "w").write("#!/bin/sh\n# written by `phosphor mentions --setup`\n"
                          "exec %s %s mention-hook\n" % (sys.executable, os.path.join(REPO, "phosphor")))
    os.chmod(HOOK, 0o755)
    print(row(OK, "hook", HOOK))
    if not os.path.exists(MHCONF):
        print(row(WARN, "matterhorn", "no config.ini yet", note="set it up, then run this again"))
        return 1
    lines = open(MHCONF).read().splitlines()
    keep = [l for l in lines if not l.strip().startswith(("activityNotifyCommand", "activityNotifyVersion"))]
    at = next((i + 1 for i, l in enumerate(keep) if l.strip().lower() == "[mattermost]"), len(keep))
    keep[at:at] = ["activityNotifyCommand = " + HOOK, "activityNotifyVersion = 2"]
    open(MHCONF + ".bak", "w").write("\n".join(lines) + "\n")
    open(MHCONF, "w").write("\n".join(keep) + "\n")
    os.chmod(MHCONF, 0o600)
    print(row(OK, "matterhorn", "hook set in config.ini", note="backup: config.ini.bak"))
    print("  " + DIM + "It takes effect when matterhorn restarts (phosphor restart), and only for" + RST)
    print("  " + DIM + "the notifications your Mattermost preferences allow (mentions, DMs...)." + RST)
    return 0

# ── prepare notes ────────────────────────────────────────────
def cfg():
    return ((deckconf.load()[0] or {}).get("mentions") or {})

def state(t):
    try: return open(os.path.join(PREP, "%s" % t)).read().strip()
    except OSError: return ""

def set_state(t, s):
    os.makedirs(PREP, exist_ok=True)
    open(os.path.join(PREP, "%s" % t), "w").write(s)

def prepare(t):
    """Run `prepare` for the notification stamped t (called detached)."""
    c = cfg()
    cmd = c.get("prepare")
    e = next((x for x in entries() if str(x.get("t")) == str(t)), None)
    if not cmd or not e:
        set_state(t, "failed: no prepare command" if not cmd else "failed: not found"); return 1
    set_state(t, "running")
    prompt = c.get("prompt", PROMPT).format(sender=e.get("from", "?"), message=e.get("message", ""))
    try:
        # a login shell: the deck's own environment lacks ~/.local/bin, where
        # assistant CLIs usually live
        r = subprocess.run(["bash", "-lc", cmd], input=prompt, capture_output=True, text=True,
                           timeout=int(c.get("timeout", 600)))
        out, err, rc = r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "timed out", 1
    if rc == 0 and out:
        import notes
        title = "@%s: %s" % (e.get("from", "?"), e.get("message", "")[:70])
        notes.append(WORK, "summary", c.get("by", "assistant"), title, out)
        set_state(t, "ready")
        with open(EVENTS, "a") as f:
            f.write("\twork notes ready: @%s\n" % e.get("from", "?"))
        return 0
    set_state(t, "failed: " + ((err or out).splitlines() or ["no output"])[-1][:60])
    return 1

def start_prepare(t):
    subprocess.Popen([sys.executable, os.path.join(REPO, "phosphor"), "mentions", "--prepare", str(t)],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    set_state(t, "running")

# ── the viewer ───────────────────────────────────────────────
def go(sess):
    tab = chat_tab(sess)
    if tab:
        zj(sess, "go-to-tab-name", tab[1])
        zj(sess, "focus-pane-id", tab[3])
    mark_seen()

def getkey(timeout):
    """A key, ("TAP", x, y), "WUP"/"WDN", or None."""
    k = ui_getkey(timeout)
    if isinstance(k, tuple):
        if not k[4]: return None
        return {64: "WUP", 65: "WDN"}.get(k[1]) or (("TAP", k[2], k[3]) if k[1] == 0 else None)
    return k

def render(w, sel):
    """Lines and, for each, the entry index it belongs to (newest first)."""
    s, lines, owner = seen(), [], []
    for i, e in enumerate(reversed(entries())):
        when = time.strftime("%a %H:%M", time.localtime(e.get("t", 0)))
        new = e.get("t", 0) > s
        st = state(e.get("t"))
        tag = (RED + "@" + RST) if e.get("mention") else (DIM + "·" + RST)
        head = (" %s %s  %s%s" % ("@" if e.get("mention") else "·", e.get("from", "?"), when, " · new" if new else ""))
        if i == sel:
            lines.append("\x1b[7m" + pad(head, w - 1) + RST)
        else:
            lines.append(" " + tag + " " + (BLOOM if new else FG) + e.get("from", "?") + RST
                         + DIM + "  " + when + (" · new" if new else "") + RST)
        owner.append(i)
        for t in textwrap.wrap(e.get("message", ""), max(20, w - 4))[:4]:
            lines.append("   " + (FG if new else MUTE) + t + RST); owner.append(i)
        if st:
            lines.append("   " + (RED if st.startswith("failed") else AMB) + STATE_TXT.get(st, st) + RST)
            owner.append(i)
        lines.append(""); owner.append(None)
    if not lines:
        return [DIM + " nothing yet. Notifications land here as they arrive." + RST], [None]
    return lines, owner

def view():
    sess = os.environ.get("ZELLIJ_SESSION_NAME") or \
        ((deckconf.load()[0] or {}).get("deck") or {}).get("session", "deck")
    if not sys.stdin.isatty():
        for l in render(78, -1)[0]: print(l)
        return 0
    off, sel = 0, 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((70, 20))
            w = min(cols, 100)
            ents = list(reversed(entries()))
            sel = max(0, min(sel, len(ents) - 1)) if ents else 0
            lines, owner = render(w, sel)
            can_prep = bool(cfg().get("prepare"))
            buttons = [("go", " [ go to chat ] ")] + ([("prep", " [ prepare notes ] ")] if can_prep else []) \
                + [("work", " [ work notes ] ")]
            body = max(3, rows - 4)
            first = owner.index(sel) if sel in owner else 0
            if first < off: off = first
            if first >= off + body: off = first - body + 2
            off = max(0, min(off, max(0, len(lines) - body)))
            n = unread()
            head = BLOOM + " MENTIONS" + RST + DIM + ("   %d new" % n if n else "   all seen") + "   read-only" + RST
            bar, spans, x = "", [], 1
            for key, label in buttons:
                spans.append((x, x + len(label) - 1, key)); bar += AMB + label + RST + " "; x += len(label) + 1
            foot = DIM + " j/k pick · Enter chat" + (" · p prepare" if can_prep else "") + " · w work notes · q quit" + RST
            out = [head, RULE + " " + "─" * max(0, w - 2) + RST] + lines[off:off + body]
            out = out[:rows - 2] + [bar, foot]
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out[:rows]) + "\x1b[K\x1b[J"); sys.stdout.flush()
            bar_row = len(out) - 1                 # 1-based row of the button bar
            k = getkey(2.0)
            act = None
            if isinstance(k, tuple):
                _, tx, ty = k
                if ty == bar_row:
                    act = next((key for a, b, key in spans if a <= tx <= b), None)
                elif 3 <= ty < 3 + body:
                    li = off + ty - 3
                    if 0 <= li < len(owner) and owner[li] is not None: sel = owner[li]
            elif k in ("q", "\x03", "\x1b"): break
            elif k in ("j", "\x1b[B"): sel += 1
            elif k in ("k", "\x1b[A"): sel -= 1
            elif k == "WDN": off += 3
            elif k == "WUP": off -= 3
            elif k in ("\r", "\n"): act = "go"
            elif k == "p": act = "prep"
            elif k == "w": act = "work"
            if act == "go": go(sess)
            elif act == "prep" and can_prep and ents: start_prepare(ents[sel].get("t"))
            elif act == "work":
                sys.stdout.write("\x1b[?1006l\x1b[?1000l"); sys.stdout.flush()
                subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "notes", "--book", "work"])
                sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")
    return 0

def main():
    a = sys.argv[1:]
    if "--setup" in a:
        return setup()
    if "--prepare" in a:
        i = a.index("--prepare")
        return prepare(a[i + 1] if i + 1 < len(a) else "")
    return view()
