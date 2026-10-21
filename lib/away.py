"""While you were away (issue #77): coming into the deck, one screen with
what happened since you last left it -- fleet alerts that came and went
and what's wrong there now that wasn't, pipelines that finished, chat
notifications, other notifications, notes others took, a newer phosphor.

Unlike `phosphor digest` it asks no assistant and no network: everything
comes from what the deck already keeps (the events file, fleet.json, the
CI card's last answer, the chat feed, the notebook, update.json), so a dead
fleet or forge never slows getting in. Any key or a tap closes it, and that
key is swallowed, never typed into the deck.

When you were last here is ~/.local/share/phosphor/seen.json: the time,
and what the fleet, the pipelines and phosphor looked like then, to tell
what changed. It's written on the way in and again on the way out (a
dropped ssh link included).

Never shown: the first time in, with nothing to say (a noisy screen gets
skipped forever), without a terminal, or with `away = false` in [deck].
"""
import json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf, events, ui
from sanitize import clean

PER = 5          # lines per section; the rest is "+N more"
CI_DONE = ("SUCCESS", "FAILED", "FAILURE", "CANCELED", "CANCELLED", "SKIPPED")


def path():
    return os.path.join(deckconf.data_dir(), "seen.json")


def load():
    try:
        with open(path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("t"), (int, float)) else None
    except (OSError, ValueError):
        return None


def problems():
    """{"host kind": detail} for what's past its red line on the fleet now,
    what you snoozed left out; None when FLEET isn't running here."""
    import glance, snooze
    try:
        with open(glance.CACHE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - d.get("t", 0) > 90:
        return None
    quiet, out = snooze.load(), {}
    for name, h in (d.get("hosts") or {}).items():
        for k, n, detail, _ in (glance.findings(name, h) if h else ()):
            if not snooze.holds(quiet, name, k, n):
                out["%s %s" % (name, k)] = "%s: %s%s" % (name, "down, " if k == "down" else "", detail)
    return out


def pipelines():
    """{name: [sha, status, commit]} from the CI card's last answer
    (ci --json keeps it), None without one."""
    try:
        with open(os.path.join(deckconf.cache_dir(), "answer-ci.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return {p.get("name") or "?": [p.get("sha") or "", p.get("status") or "", p.get("commit") or ""]
            for p in d.get("pipelines") or [] if isinstance(p, dict)}


def behind():
    import version
    c = version.cached()
    return {"behind": c.get("behind") or 0, "latest": c.get("latest") or ""}


def snapshot(now=None):
    """What seen.json keeps: the time, and what's compared next time."""
    return {"t": time.time() if now is None else now, "problems": problems(),
            "ci": pipelines(), "phosphor": behind()}


def saw(now=None):
    """You're here (or just left): the mark moves to now. A part that
    can't be read now (FLEET not running) keeps what it said last."""
    old, new = load() or {}, snapshot(now)
    for k in ("problems", "ci"):
        if new[k] is None:
            new[k] = old.get(k)
    p = path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(new, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def stamp(t, now):
    lt, ln = time.localtime(t), time.localtime(now)
    return time.strftime("%H:%M" if lt[:3] == ln[:3] else "%a %H:%M", lt)


def fleet(seen, now, evs):
    """Alerts in order, then what's wrong now that wasn't, and what was
    and isn't anymore."""
    out = [(stamp(t, now), x) for t, tab, x in evs if tab in ("SYS", "FLEET") and not x.endswith("(snoozed)")]
    was, now_p = seen.get("problems"), problems()
    if was is not None and now_p is not None:
        out += [("now", d) for k, d in sorted(now_p.items()) if k not in was]
        out += [("gone", d) for k, d in sorted(was.items()) if k not in now_p]
    return out


def ci(seen):
    """Pipelines that finished a run you haven't seen."""
    was, now_p = seen.get("ci"), pipelines()
    if was is None or now_p is None:
        return []
    out = []
    for name, (sha, st, commit) in sorted(now_p.items()):
        if st.upper() in CI_DONE and was.get(name, [None, None])[:2] != [sha, st]:
            out.append((st.upper(), "%s  %s %s" % (name, sha[:8], commit)))
    return out


def chat(seen, now):
    import mentions
    got = [e for e in mentions.entries() if (e.get("t") or 0) > seen["t"]]
    return [(stamp(e["t"], now), "@%s: %s" % (e.get("from", "?"), e.get("message", ""))) for e in got]


def notebook(seen):
    """Entries someone else wrote: yours, you know about."""
    import digest, notes
    me = os.environ.get("USER", "me")
    return [(e["by"], "%s: %s" % (e["kind"], e["title"] or (e["body"][0] if e["body"] else "")))
            for e in notes.entries()
            if e["by"] != me and (digest.when(e["when"]) or 0) >= seen["t"]]


def sections(seen, now=None):
    """[(title, [(left, text)])], only the ones with something in them."""
    now = time.time() if now is None else now
    evs = events.since(seen["t"])
    other = [(stamp(t, now), (tab + "  " if tab else "") + x) for t, tab, x in evs
             if tab not in ("SYS", "FLEET", "COMMS")]
    out = [("FLEET", fleet(seen, now, evs)), ("PIPELINES", ci(seen)), ("CHAT", chat(seen, now)),
           ("NOTIFICATIONS", other), ("NOTEBOOK", notebook(seen))]
    was, b = seen.get("phosphor") or {}, behind()
    if b["behind"] and b != was:
        out.append(("PHOSPHOR", [("", "%s is out, you're %d behind: phosphor update" % (b["latest"], b["behind"]))]))
    return [(t, rows) for t, rows in out if rows]


def ago(secs):
    m = int(secs // 60)
    return "%d min" % m if m < 120 else ("%d h" % (m // 60) if m < 48 * 60 else "%d days" % (m // 1440))


def frame(seen, secs, cols, rows, now=None):
    """The screen's lines, at most rows of them, each fit to cols."""
    now = time.time() if now is None else now
    w = max(20, cols)
    out = ui.topbar("WHILE YOU WERE AWAY", "since %s, %s ago" % (stamp(seen["t"], now), ago(now - seen["t"])),
                    "", w)
    for title, got in secs:
        out.append("")
        out.append("  " + ui.BLOOM + title + ui.RST)
        shown = got[-PER:] if len(got) > PER else got
        if len(got) > PER:
            out.append("    " + ui.DIM + "+%d before these" % (len(got) - PER) + ui.RST)
        left = max(len(l) for l, _ in shown)
        for l, text in shown:
            col = ui.RED if l in ("now", "FAILED", "FAILURE") else ui.FG
            line = "    " + ui.DIM + l.ljust(left) + ui.RST + "  " + col + clean(text) + ui.RST
            out.append(ui.vcut(line, w))
    foot = "  " + ui.DIM + "any key: into the deck" + ui.RST
    if len(out) + 2 > rows:
        out = out[:max(1, rows - 3)] + ["  " + ui.DIM + "..." + ui.RST]
    return out + ["", foot]


def wanted(prof):
    return (((prof or {}).get("deck") or {}).get("away", True) is not False
            and sys.stdin.isatty() and sys.stdout.isatty())


def show(prof):
    """The screen, if there's something to say; then you're here."""
    seen = load()
    try:
        secs = sections(seen) if seen and wanted(prof) else []
    except Exception:
        import dlog
        dlog.crash("AWAY")
        secs = []
    if secs:
        cols, rows = shutil.get_terminal_size((80, 24))
        w = sys.stdout.write
        w("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J")
        w("\r\n".join(frame(seen, secs, cols, rows))); sys.stdout.flush()
        try:
            end = time.monotonic() + 600     # nobody there: go in anyway
            while time.monotonic() < end:
                k = ui.getkey(timeout=end - time.monotonic(), mouse=True)
                if k is not None and k not in ("WUP", "WDN"):
                    break                    # a release or the wheel isn't an answer
        except (KeyboardInterrupt, OSError):
            pass
        finally:
            w("\x1b[?1000l\x1b[?1006l\x1b[2J\x1b[?25h\x1b[?1049l"); sys.stdout.flush()
    saw()
