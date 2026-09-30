#!/usr/bin/env python3
"""phosphor prom - Prometheus gauges in a pane.

Reads [prometheus] from the profile (url, interval, [[prometheus.gauges]]),
asks Prometheus each query and draws one card per gauge: a bar, an arc or a
sparkline, colored by its warn and crit thresholds.

    phosphor prom           the panel, redrawn every interval
    phosphor prom --once    one frame on stdout
"""
import json, os, re, shutil, sys, time, urllib.request, urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, BLOOM, AMB, RED, RULE, RST, vlen, not_set_up, topbar, card as ui_card
import deckconf

SPARKS = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")

# Prometheus watching itself: what [prometheus] with a url and no gauges shows
DEFAULT_METRICS = [
    {"name": "Prometheus up", "type": "arc", "query": 'up{job="prometheus"}',
     "min": 0, "max": 1, "warn": 2, "crit": 3, "unit": ""},
    {"name": "TSDB head series", "type": "gauge", "query": "prometheus_tsdb_head_series",
     "min": 0, "max": 100000, "warn": 70000, "crit": 90000, "unit": ""},
    {"name": "Memory alloc", "type": "gauge", "query": "go_memstats_alloc_bytes / 1024 / 1024",
     "min": 0, "max": 256, "warn": 128, "crit": 200, "unit": "MB"},
    {"name": "HTTP requests/s", "type": "sparkline",
     "query": "sum(rate(prometheus_http_requests_total[1m]))",
     "min": 0, "max": 50, "warn": 35, "crit": 45, "unit": ""},
]

HISTORY = {}  # query -> its last values, for sparklines

def settings(prof):
    """(url, gauges, interval), or None with no [prometheus] in the profile."""
    if "prometheus" not in (prof or {}):
        return None
    conf = prof["prometheus"]
    return (conf.get("url", "http://localhost:9090"), conf.get("gauges", DEFAULT_METRICS),
            conf.get("interval", 5))

def unset(cols):
    """No [prometheus] yet: say what this is and how to turn it on, not four
    "Connection refused" cards against a Prometheus you never said you had."""
    return not_set_up("PROMETHEUS",
        "Your Prometheus queries, one card each: a bar, an arc or a sparkline, "
        "amber and red past the thresholds you give it.",
        "a Prometheus to ask, and what to ask it.",
        ['[prometheus]', 'url = "http://localhost:9090"', '',
         '[[prometheus.gauges]]', 'name  = "Load"', 'query = "node_load1"',
         'max = 8', 'warn = 4', 'crit = 6'],
        "phosphor prom", max(16, cols))

def query_prometheus(url, query, timeout=4):
    """(value, None) or (None, why): the first series of an instant query."""
    try:
        api_url = url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
        req = urllib.request.Request(api_url, headers={"User-Agent": "phosphor-prom"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "success":
            return None, data.get("error", "query error")
        result = data.get("data", {}).get("result", [])
        if not result:
            return None, "no data"
        return float(result[0]["value"][1]), None
    except Exception as e:
        return None, re.sub(r"^\[Errno -?\d+\] ", "", str(getattr(e, "reason", None) or e))

def get_color_and_tag(val, err, min_v, max_v, warn, crit, unit):
    if err is not None or val is None:
        return MUTE, "ERR", "N/A", 0.0
    pct = max(0.0, min(1.0, (val - min_v) / max(1e-6, (max_v - min_v))))
    if val >= crit:
        col, tag = RED, "CRIT"
    elif val >= warn:
        col, tag = AMB, "WARN"
    else:
        col, tag = PH, "OK"
    num = ("%.1f" % val).rstrip("0").rstrip(".")
    return col, tag, num + unit, pct

def cut(s, n):
    return s if len(s) <= n else s[:max(0, n - 1)] + "…"

def card(name, tag, col, body, w):
    return ui_card(name, tag, body, w, col)

def why(err, inner):
    return [" " + MUTE + cut(err, inner - 2) + RST] if err else []

def draw_gauge_bar(name, val, err, min_v, max_v, warn, crit, unit, width):
    col, tag, disp, pct = get_color_and_tag(val, err, min_v, max_v, warn, crit, unit)
    inner = width - 2
    bar_w = max(1, inner - max(7, len(disp)) - 4)
    fill = int(round(pct * bar_w))
    bar = col + "█" * fill + RULE + "░" * (bar_w - fill) + RST
    body = [" " + col + disp.rjust(7) + RST + " " + bar + " "] + why(err, inner)
    return card(name, tag, col, body, width)

def draw_gauge_arc(name, val, err, min_v, max_v, warn, crit, unit, width):
    col, tag, disp, pct = get_color_and_tag(val, err, min_v, max_v, warn, crit, unit)
    inner = width - 2
    arc_w = max(1, inner - 6)
    fill = int(round(pct * arc_w))
    body = ["  ╭" + col + "━" * fill + RULE + "─" * (arc_w - fill) + RST + "╮",
            "  │" + col + cut(disp, arc_w).center(arc_w) + RST + "│"] + why(err, inner)
    return card(name, tag, col, body, width)

def draw_sparkline(name, val, err, min_v, max_v, warn, crit, unit, width, q_key):
    col, tag, disp, pct = get_color_and_tag(val, err, min_v, max_v, warn, crit, unit)
    inner = width - 2
    hist = HISTORY.setdefault(q_key, deque(maxlen=200))
    if val is not None:
        hist.append(val)
    spark_w = max(1, inner - max(7, len(disp)) - 4)
    chars = []
    for v in list(hist)[-spark_w:]:
        p = max(0.0, min(1.0, (v - min_v) / max(1e-6, (max_v - min_v))))
        chars.append(SPARKS[int(round(p * (len(SPARKS) - 1)))])
    body = [" " + col + disp.rjust(7) + " " + "".join(chars).rjust(spark_w) + RST + " "] + why(err, inner)
    return card(name, tag, col, body, width)

def frame(url, cols, rows, results):
    """The screen as lines, none wider than cols (at least 16)."""
    w = max(16, cols)
    out = topbar("PROMETHEUS", url, time.strftime("%H:%M:%S"), w)
    for m, val, err in results:
        args = dict(name=m.get("name", m.get("query", "?")), val=val, err=err,
                    min_v=m.get("min", 0), max_v=m.get("max", 100),
                    warn=m.get("warn", 80), crit=m.get("crit", 90), unit=m.get("unit", ""), width=w)
        kind = m.get("type", "gauge")
        if kind == "arc":
            out += draw_gauge_arc(**args)
        elif kind == "sparkline":
            out += draw_sparkline(q_key=m.get("query", args["name"]), **args)
        else:
            out += draw_gauge_bar(**args)
    return out[:max(1, rows)]

def fetch(url, metrics):
    with ThreadPoolExecutor(max_workers=max(2, len(metrics))) as ex:
        futs = [ex.submit(query_prometheus, url, m["query"]) for m in metrics]
        return [(m,) + f.result() for m, f in zip(metrics, futs)]

def screen(cols, rows):
    """(lines, seconds to the next redraw), reading the profile afresh: a
    [prometheus] you just saved shows up without restarting the pane."""
    got = settings(deckconf.load()[0])
    if got is None:
        return unset(cols)[:max(1, rows)], 2
    url, metrics, interval = got
    return frame(url, cols, rows, fetch(url, metrics)), interval

def main():
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(screen(cols, 10000)[0]))
        return
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((80, 24))
            out, interval = screen(cols, rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")

if __name__ == "__main__":
    main()
