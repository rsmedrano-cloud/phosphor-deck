#!/usr/bin/env python3
"""phosphor usage: the two providers' answers become bars, an expired or
missing token never calls anyone, and every line fits the pane exactly.
No network: the answers are fixtures, and _post refuses to be called.

    python3 tests/usage-check.py
"""
import json, os, re, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import usage

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

calls = []
def no_network(*a, **k):
    calls.append(a[0]); raise AssertionError("network")
usage._post = no_network

now = time.time()
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))

# Claude: utilization is already "used", in percent
rows = usage.claude_rows({"five_hour": {"utilization": 4.0, "resets_at": iso(now + 3600)},
                          "seven_day": {"utilization": 54.0, "resets_at": iso(now + 4 * 86400)},
                          "seven_day_opus": None})
check("claude: 5h and week, nothing for a null pool", [r[0] for r in rows] == ["5h", "week"])
check("claude: used as given", rows[1][1] == 54.0)
check("claude: reset parsed", abs(rows[0][2] - (now + 3600)) < 2)

# Antigravity: one row per pool, used = 1 - remaining, internal models left out
models = {
    "gemini-3.1-pro-high": {"displayName": "Gemini 3.1 Pro", "quotaInfo": {"remainingFraction": 0.13, "resetTime": "2026-10-01T21:02:52Z"}},
    "gemini-3-flash": {"displayName": "Gemini 3 Flash", "quotaInfo": {"remainingFraction": 0.13, "resetTime": "2026-10-01T21:02:52Z"}},
    "claude-sonnet-4-6": {"displayName": "Claude Sonnet", "quotaInfo": {"remainingFraction": 1, "resetTime": "2026-10-02T00:59:32Z"}},
    "gpt-oss-120b-medium": {"displayName": "GPT-OSS", "quotaInfo": {"remainingFraction": 1, "resetTime": "2026-10-02T00:59:32Z"}},
    "tab_flash_lite_preview": {"quotaInfo": {"remainingFraction": 1}},
    "chat_20706": {"quotaInfo": {"remainingFraction": 0.5}},
}
rows = usage.agy_rows(models)
check("agy: two pools, gemini first", [r[0] for r in rows] == ["gemini", "claude/gpt"])
check("agy: used is 1 - remaining", round(rows[0][1]) == 87 and rows[1][1] == 0)
check("agy: no models, no rows", usage.agy_rows(None) == [])

# tokens: missing = not signed in (skipped), expired = says so; neither calls out
d = tempfile.mkdtemp()
usage.CLAUDE_CREDS = os.path.join(d, "creds.json")
usage.AGY_TOKEN = os.path.join(d, "agy.json")
check("claude: no file, not signed in", usage.claude() == (None, None))
check("agy: no file, not signed in", usage.agy() == (None, None))
json.dump({"claudeAiOauth": {"accessToken": "x", "expiresAt": (now - 60) * 1000}}, open(usage.CLAUDE_CREDS, "w"))
json.dump({"token": {"access_token": "x", "expiry": iso(now - 60)}}, open(usage.AGY_TOKEN, "w"))
r = usage.claude(); check("claude: expired token says so", r[0] == [] and "open claude" in r[1])
r = usage.agy(); check("agy: expired token says so", r[0] == [] and "open agy" in r[1])
check("an expired token never reaches the network", calls == [])

# drawing: every line exactly the pane's width, wide and narrow
ansi = re.compile(r"\x1b\[[0-9;]*m")
res = [("CLAUDE", usage.claude_rows({"five_hour": {"utilization": 95, "resets_at": iso(now + 630)}}), None),
       ("ANTIGRAVITY", usage.agy_rows(models), None), ("NOBODY", None, None)]
for cols in (80, 40, 24):
    out = usage.frame(res, cols, 100, now=now)
    widths = {len(ansi.sub("", l)) for l in out[2:]}
    check("width %d: cards fit exactly (%s)" % (cols, widths), widths == {cols})
txt = ansi.sub("", "\n".join(usage.frame(res, 80, 100, now=now)))
check("a card per signed-in assistant only", "CLAUDE" in txt and "ANTIGRAVITY" in txt and "NOBODY" not in txt)
check("95% used is HIGH", "HIGH" in txt)
check("reset countdown shown", "10m" in txt)
check("nobody signed in: says so",
      "No assistant signed in" in ansi.sub("", "\n".join(usage.frame([("C", None, None)], 60, 20))))

if fails:
    print("usage-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("usage-check ok")
