#!/usr/bin/env python3
"""phosphor screen --probe (lib/probe.py): one numbered page of what a
screen can draw, for the tester trying a new kind of screen. Every number
there once, 24-bit color only from row 8 on (a client that misreads it
then spoils only the rows after), both themes shown, nothing written (but the
dispatcher's usage count).

    python3 tests/probe-check.py
"""
import os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
home = tempfile.mkdtemp()
prof = os.path.join(home, "deck.toml")
open(prof, "w").write('[deck]\nsession = "probe"\ntheme = "p31"\n')
env = dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof, TERM="xterm-256color", COLUMNS="50")
for v in ("PHOSPHOR_THEME", "NO_COLOR", "ZELLIJ"):
    env.pop(v, None)

fails = []
def need(what, ok):
    if not ok: fails.append(what)

r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "screen", "--probe"],
                   capture_output=True, text=True, timeout=30, env=env)
out = r.stdout.splitlines()
need("exits 0", r.returncode == 0)
nums = [int(m.group(1)) for l in out for m in [re.match(r"\s*(\d+)  ", re.sub(r"\x1b\[[0-9;]*m", "", l))] if m]
need("rows 0 to 10, each once: %s" % nums, nums == list(range(11)))
row = lambda n: next(i for i, l in enumerate(out) if re.match(r"\s*%d  " % n, l))
need("no 24-bit color before row 8",
     not any(re.search(r"\x1b\[[34]8;2;", l) for l in out[:row(8)]))
need("the deck's theme, then paper", "deck, p31" in out[row(9)] and "deck, paper" in out[row(10)])
need("line 0 says TERM and the size", "TERM xterm-256color" in out[row(0)] and "50x" in out[row(0)])
need("a 50-column screen gets lines that fit",
     all(len(re.sub(r"\x1b\[[0-9;]*m", "", l)) <= 50 for l in out[row(9):row(10) + 9]))
written = [os.path.relpath(os.path.join(d, f), home) for d, _, fs in os.walk(home) for f in fs]
need("nothing written but the usage count: %s" % written,
     set(written) <= {"deck.toml", ".cache/phosphor/stats.json", ".cache/phosphor/stats.json.lock"})

for f in fails:
    print("FAIL", f)
print("probe-check: %s" % ("FAIL" if fails else "ok"))
sys.exit(1 if fails else 0)
