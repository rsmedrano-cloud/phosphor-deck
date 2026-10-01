#!/usr/bin/env python3
"""phosphor usage - how much of your AI assistants' plan you've used.

One card per assistant this machine is signed into: Claude Code (its
5-hour window and the week) and Antigravity (each quota pool: Gemini, and
the Claude/GPT models it also offers, with when each one refills).

It reads the token each CLI already keeps (~/.claude/.credentials.json,
~/.gemini/antigravity-cli/antigravity-oauth-token) and asks that same
provider -- the question the CLI itself asks for its own /usage screen.
Read-only: it never refreshes a token (that would rotate it under the CLI's
feet); an expired one says "open claude (or agy) once" and waits.

    phosphor usage          the panel, refreshed every couple of minutes
    phosphor usage --once   one frame on stdout
"""
import json, os, shutil, sys, time, urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, AMB, RED, RULE, RST, cut, topbar, card
import ui

HOME = os.path.expanduser("~")
CLAUDE_CREDS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude"),
                            ".credentials.json")
AGY_TOKEN = os.path.join(HOME, ".gemini", "antigravity-cli", "antigravity-oauth-token")
CLAUDE_URL = "https://api.anthropic.com/api/oauth/usage"
AGY_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:"
FETCH_EVERY = 120   # seconds between asking the providers; the countdowns redraw every 15

def _ts(s):
    """An RFC 3339 time (2026-10-02T00:40:00.16+00:00, ...Z) as epoch seconds."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None

def _post(url, token, body=None, headers=None, agent="phosphor-usage"):
    h = {"Authorization": "Bearer " + token, "User-Agent": agent}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())

def _why(e):
    code = getattr(e, "code", None)
    if code in (401, 403):
        return "signed out or token expired"
    return str(getattr(e, "reason", None) or e)[:60]

# -- Claude Code ------------------------------------------------------------

def claude_rows(data):
    """The usage answer as [(label, used 0..100, resets_at epoch)]."""
    rows = []
    for key, label in (("five_hour", "5h"), ("seven_day", "week"),
                       ("seven_day_opus", "week opus"), ("seven_day_sonnet", "week sonnet")):
        v = (data or {}).get(key)
        if isinstance(v, dict) and v.get("utilization") is not None:
            rows.append((label, float(v["utilization"]), _ts(v.get("resets_at"))))
    return rows

def claude():
    """(rows, error); (None, None) when Claude Code was never signed in here."""
    try:
        with open(CLAUDE_CREDS) as f:
            o = json.load(f).get("claudeAiOauth") or {}
    except (OSError, ValueError):
        return None, None
    if not o.get("accessToken"):
        return None, None
    if o.get("expiresAt") and o["expiresAt"] / 1000 < time.time():
        return [], "token expired: open claude once"
    try:
        return claude_rows(_post(CLAUDE_URL, o["accessToken"],
                                 headers={"anthropic-beta": "oauth-2025-04-20"})), None
    except Exception as e:
        return [], _why(e)

# -- Antigravity ------------------------------------------------------------

def _family(model_id):
    m = model_id.lower()
    for fam in ("gemini", "claude", "gpt"):
        if m.startswith(fam):
            return fam
    return None

def agy_rows(models):
    """fetchAvailableModels' models as [(label, used 0..100, resets_at)]: one
    row per quota pool (the models that share a fraction and a refill time),
    named after the families in it. Internal models without a display name
    (tab completion and the like) are left out."""
    pools = {}
    for mid, m in (models or {}).items():
        q, fam = m.get("quotaInfo") or {}, _family(mid)
        if not m.get("displayName") or fam is None or "remainingFraction" not in q:
            continue
        key = (round(float(q["remainingFraction"]), 4), q.get("resetTime"))
        pools.setdefault(key, set()).add(fam)
    order = {"gemini": 0, "claude": 1, "gpt": 2}
    rows = [("/".join(sorted(fams, key=order.get)), (1 - frac) * 100, _ts(reset))
            for (frac, reset), fams in pools.items()]
    return sorted(rows, key=lambda r: min(order[f] for f in r[0].split("/")))

_agy_project = {}

def agy():
    """(rows, error); (None, None) when Antigravity was never signed in here."""
    try:
        with open(AGY_TOKEN) as f:
            t = (json.load(f).get("token") or {})
    except (OSError, ValueError):
        return None, None
    tok = t.get("access_token")
    if not tok:
        return None, None
    exp = _ts(t.get("expiry"))
    if exp and exp < time.time():
        return [], "token expired: open agy once"
    try:
        if tok not in _agy_project:
            lc = _post(AGY_URL + "loadCodeAssist", tok, {"metadata": {"ideType": "ANTIGRAVITY"}},
                       agent="antigravity")
            _agy_project.clear()
            _agy_project[tok] = lc.get("cloudaicompanionProject")
        proj = _agy_project[tok]
        # the quota answer is only given to antigravity's own user agent
        got = _post(AGY_URL + "fetchAvailableModels", tok, {"project": proj} if proj else {},
                    agent="antigravity")
        return agy_rows(got.get("models")), None
    except Exception as e:
        return [], _why(e)

# -- drawing ----------------------------------------------------------------

def left(at, now):
    """Seconds until a reset as 3h12m / 4d07h / 25m."""
    if at is None:
        return ""
    s = max(0, int(at - now))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return "%dd%02dh" % (d, h) if d else ("%dh%02dm" % (h, m) if h else "%dm" % m)

def bar_row(label, used, at, w, now):
    col = RED if used >= 90 else AMB if used >= 75 else PH
    pct = "%3d%%" % round(used)
    rst = left(at, now)
    lab_w = 6 if w < 40 else 11
    tail = (" ↺" + rst.rjust(6)) if rst and w >= 28 else ""
    bar_w = max(1, w - 4 - lab_w - len(pct) - len(tail))
    fill = int(round(max(0, min(100, used)) / 100 * bar_w))
    return (" " + MUTE + cut(label, lab_w).ljust(lab_w) + RST + " "
            + col + "█" * fill + RULE + "░" * (bar_w - fill) + RST
            + " " + col + pct + RST + DIM + tail + RST)

def frame(results, cols, rows, now=None, stale=False):
    """results: [(title, rows or None, error)]; None rows = not signed in, skipped."""
    now = now or time.time()
    w = max(20, cols)
    shown = [(t, r, e) for t, r, e in results if r is not None or e]
    out = topbar("USAGE", "your assistants' plans", "stale" if stale else time.strftime("%H:%M"), w)
    if not shown:
        out += ["", " " + MUTE + cut("No assistant signed in on this machine (claude, agy).", w - 2) + RST]
        return out[:max(1, rows)]
    for title, rws, err in shown:
        body = [bar_row(l, u, a, w - 2, now) for l, u, a in (rws or [])]
        if err:
            body.append(" " + (AMB if rws else MUTE) + cut(err, w - 4) + RST)
        hi = max([u for _, u, _ in rws or []] + [0])
        tag, col = ("ERR", MUTE) if err and not rws else (("HIGH", RED) if hi >= 90 else
                    ("WARN", AMB) if hi >= 75 else ("OK", PH))
        out += card(title, tag, body or [""], w, col)
    return out[:max(1, rows)]

def collect():
    c, a = claude(), agy()
    return [("CLAUDE", c[0], c[1]), ("ANTIGRAVITY", a[0], a[1])]

def main():
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(frame(collect(), cols, 10000)))
        return
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    last, got = 0, []
    loud = ui.quiet()
    try:
        while True:
            if time.time() - last >= FETCH_EVERY:
                new = collect()
                # a failed round keeps the last good rows, marked by their error
                got = [(t, r if r or not old or old[1] is None else old[1], e)
                       for (t, r, e), old in zip(new, got or [(None, None, None)] * len(new))]
                last = time.time()
            cols, rows = shutil.get_terminal_size((80, 24))
            out = frame(got, cols, rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            ui.idle(15)
    except KeyboardInterrupt:
        pass
    finally:
        loud()
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")

if __name__ == "__main__":
    main()
