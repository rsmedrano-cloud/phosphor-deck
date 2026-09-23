#!/usr/bin/env python3
"""phosphor pulse - the fleet's heartbeat.

Not decoration: the wave follows the machines' real load and turns amber
or red when something is wrong.
"""
import json, math, os, random, shutil, sys, time
from collections import deque

HOME  = os.path.expanduser("~")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, BLOOM, AMB, RED, RULE, RST
import deckconf

CACHE = os.path.join(deckconf.cache_dir(), "fleet.json")

# braille: 2 columns x 4 rows of sub-pixels per character. Fonts without
# Braille draw them as boxes with a hex number: `graphs = "blocks"` in the
# profile switches to half blocks, which every font has.
DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
HALF = {(True, False): "▀", (False, True): "▄", (True, True): "█"}

def read_state():
    """(normalized load, level, reason). level: 0 ok, 1 warning, 2 critical."""
    try:
        with open(CACHE) as f: d = json.load(f)
    except Exception:
        return 0.15, 0, "no data"
    if time.time() - d.get("t", 0) > 90:
        return 0.15, 1, "stale data"
    hosts, load, lvl, why = d.get("hosts", {}), 0.0, 0, "nominal"
    n = 0
    for name, h in hosts.items():
        if not h.get("ok"):
            lvl = max(lvl, 2); why = "%s unreachable" % name; continue
        n += 1
        load += h.get("CPU", 0) / 100.0
        mp = h.get("MEMU", 0) / max(1, h.get("MEMT", 1))
        load += mp * 0.5
        for _, pct, _ in h.get("mnt", []):
            if pct >= 92 and lvl < 2: lvl, why = 2, "%s disk %d%%" % (name, pct)
            elif pct >= 85 and lvl < 1: lvl, why = 1, "%s disk %d%%" % (name, pct)
    if n: load /= n
    return min(1.0, max(0.05, load)), lvl, why

def main():
    braille = ((deckconf.load()[0] or {}).get("deck") or {}).get("graphs", "braille") != "blocks"
    cols, rows = shutil.get_terminal_size((80, 8))
    hist = deque(maxlen=400)
    phase, last, load, lvl, why = 0.0, 0.0, 0.2, 0, "nominal"
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((80, 8))
            h = max(3, rows - 4)
            w = max(20, cols - 2)
            if time.time() - last > 3:
                load, lvl, why = read_state(); last = time.time()
            col = (PH, AMB, RED)[lvl]
            glow = (BLOOM, AMB, RED)[lvl]

            amp  = 0.18 + load * 0.72          # amplitude and speed follow the load
            freq = 0.18 + load * 0.55
            phase += freq
            v = math.sin(phase) * amp
            v += math.sin(phase * 2.7) * amp * 0.28
            v += random.uniform(-0.05, 0.05) * (1 + load)
            if lvl == 2 and random.random() < 0.10:      # alarm spike
                v += random.choice((-1, 1)) * 0.9
            hist.append(max(-1.0, min(1.0, v)))

            per = 4 if braille else 2
            sub_h = h * per
            grid = [[0] * (w) for _ in range(h)]
            data = list(hist)[-w * 2:]
            for i, val in enumerate(data):
                x = i // 2
                if x >= w: break
                y = int((1 - (val + 1) / 2) * (sub_h - 1))
                cy, sy = y // per, y % per
                if 0 <= cy < h:
                    grid[cy][x] |= DOTS[sy][i % 2] if braille else (1 << sy)

            out = [RULE + "╭" + "─" * w + "╮" + RST]
            for r in range(h):
                if braille:
                    line = "".join(chr(0x2800 + b) if b else " " for b in grid[r])
                else:
                    line = "".join(HALF.get((bool(b & 1), bool(b & 2)), " ") for b in grid[r])
                out.append(RULE + "│" + RST + col + line + RST + RULE + "│" + RST)
            state = ("NOMINAL", "ELEVATED", "ALERT")[lvl]
            tag = " %s · %s " % (state, why)
            bar = "─" * max(0, w - len(tag))
            out.append(RULE + "╰" + bar + RST + glow + tag + RST + RULE + "╯" + RST)
            # Never more lines than rows: the pane would pile up scrollback.
            out = out[:max(1, rows)]
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(0.09)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")

if __name__ == "__main__":
    main()
