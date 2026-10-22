"""Service checks: does it answer? `[[hosts.checks]]` in the profile, a
URL or a TCP port, polled from the brain by the deck's own FLEET worker
(whichever poller writes fleet.json). A check that stops answering joins
its host's why list (glance.findings), so FLEET's card, glance, fleet
--json, the adjutant, push and 'while you were away' all say it.

Binary on purpose: it answers or it doesn't. No latency history, no
certificates (https is fetched without verifying one: a self-signed box
still answers), not an Uptime Kuma. An HTTP answer counts unless it's a
5xx (a proxy's 502 is the service behind it not answering).

    [[hosts]]
    name = "db-box"
    ssh  = "db-box"

    [[hosts.checks]]
    name = "jellyfin"
    url  = "http://db-box:8096/health"

    [[hosts.checks]]
    name = "postgres"
    port = 5432             # on the host's ip, else its ssh HostName

Results go to checks.json in the cache folder, next to fleet.json; the
profile is read again every round, so a new check needs no restart.
"""
import json, os, socket, ssl, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf
from sanitize import clean_tree

INTERVAL   = 30
TIMEOUT    = 5
STALE      = 120   # an older checks.json is a worker that stopped: nothing failing
FAIL_AFTER = 2     # one miss isn't an outage, same as a host's poll
_cache = {"mtime": None, "data": {}}
_addr = {}         # ssh target -> its HostName, asked once

def path():
    return os.path.join(deckconf.cache_dir(), "checks.json")

def label(c):
    """A check's name: its own, else what it points at."""
    if c.get("name"):
        return str(c["name"])
    if c.get("url"):
        return urllib.parse.urlsplit(str(c["url"])).netloc or str(c["url"])
    return "port %s" % c.get("port")

def address(h):
    """Where a port check connects on host h: its ip, the brain's own
    loopback, else what ssh would connect to (`ssh -G`), else its name."""
    if h.get("ip"):
        return str(h["ip"])
    if h.get("local"):
        return "127.0.0.1"
    t = str(h.get("ssh") or h["name"])
    if t not in _addr:
        _addr[t] = t
        try:
            out = subprocess.run(["ssh", "-G", t], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                k, _, v = line.partition(" ")
                if k == "hostname" and v.strip():
                    _addr[t] = v.strip()
                    break
        except (OSError, subprocess.SubprocessError):
            pass
    return _addr[t]

def specs(prof):
    """{host: [(name, check)]} for every polled host's checks; check is
    ("url", URL) or ("port", (address, port)). What isn't one is left out
    (profcheck says why)."""
    polled = {n for n, _ in deckconf.fleet_hosts(prof)}
    out = {}
    for h in deckconf.hosts(prof):
        if h.get("name") not in polled or not isinstance(h.get("checks"), list):
            continue
        for c in h["checks"]:
            if not isinstance(c, dict):
                continue
            if isinstance(c.get("url"), str) and c["url"].startswith(("http://", "https://")):
                out.setdefault(h["name"], []).append((label(c), ("url", c["url"])))
            elif isinstance(c.get("port"), int) and not isinstance(c["port"], bool) and 0 < c["port"] < 65536:
                where = str(c["host"]) if c.get("host") else address(h)
                out.setdefault(h["name"], []).append((label(c), ("port", (where, c["port"]))))
    return out

def probe(check, timeout=TIMEOUT):
    """None when it answers, else a few words on why not."""
    kind, target = check
    try:
        if kind == "port":
            socket.create_connection(target, timeout).close()
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        req = urllib.request.Request(target, headers={"User-Agent": "phosphor-check"})
        urllib.request.urlopen(req, timeout=timeout, context=ctx).close()
        return None
    except urllib.error.HTTPError as e:
        return None if e.code < 500 else "HTTP %d" % e.code
    except urllib.error.URLError as e:
        return _why(e.reason)
    except Exception as e:
        return _why(e)

def _why(e):
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, ConnectionRefusedError):
        return "refused"
    if isinstance(e, socket.gaierror):
        return "no such name"
    return (getattr(e, "strerror", None) or str(e) or type(e).__name__)[:32]

def load():
    """checks.json as written, {} when missing or stale."""
    try:
        mtime = os.path.getmtime(path())
    except OSError:
        return {}
    if mtime != _cache["mtime"]:
        try:
            with open(path()) as f:
                d = clean_tree(json.load(f))
            _cache["mtime"], _cache["data"] = mtime, d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
    d = _cache["data"]
    if time.time() - (d.get("t") or 0) > STALE:
        return {}
    return d

def results(host):
    """[{"name", "ok", "err"}] for host's checks, as of the last round."""
    r = (load().get("hosts") or {}).get(host)
    return [c for c in r if isinstance(c, dict)] if isinstance(r, list) else []

def failing(host):
    """[(name, why)] of host's checks that stopped answering."""
    return [(str(c.get("name")), c.get("err") or "no answer") for c in results(host) if c.get("ok") is False]

class Checker:
    """One round at a time: probe every check, debounce, write checks.json,
    then alert on what changed. `alert(host, ok, text)` is fleet's _alert;
    `down(host)` says when the host itself is down, its own alert saying
    it already."""
    def __init__(self, alert=None, down=None):
        self.alert, self.down = alert, down or (lambda h: False)
        self.misses, self.shown = {}, {}     # (host, name) -> misses in a row, last state settled

    def round(self, sp):
        jobs = [(h, n, c) for h, cs in sp.items() for n, c in cs]
        with ThreadPoolExecutor(max_workers=max(1, min(16, len(jobs)))) as ex:
            got = list(ex.map(lambda j: probe(j[2]), jobs)) if jobs else []
        out, went, back = {}, {}, {}
        for (h, n, _), err in zip(jobs, got):
            k = (h, n)
            self.misses[k] = self.misses.get(k, 0) + 1 if err else 0
            ok = self.misses[k] < FAIL_AFTER
            out.setdefault(h, []).append({"name": n, "ok": ok, "err": None if ok else err})
            if 0 < self.misses[k] < FAIL_AFTER:
                continue                     # a single miss: neither way yet
            was = self.shown.get(k)
            if was is not None and was != ok and not self.down(h):
                (back if ok else went).setdefault(h, []).append(n)
            self.shown[k] = ok
        live = set((h, n) for h, n, _ in jobs)
        for k in [k for k in self.shown if k not in live]:      # taken out of the profile
            self.shown.pop(k); self.misses.pop(k, None)
        write({"t": time.time(), "hosts": out})
        for h, names in went.items():
            self._say(h, False, "%s: %s not answering" % (h, ", ".join(names)))
        for h, names in back.items():
            self._say(h, True, "%s: %s answering again" % (h, ", ".join(names)))
        return out

    def _say(self, host, ok, text):
        if self.alert:
            self.alert(host, ok, text)

def write(d):
    try:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        tmp = "%s.%d.tmp" % (path(), os.getpid())
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, path())
    except OSError as e:
        import dlog
        dlog.event_throttled("CHECKS", "write-failed", str(e)[:60])

def runner(alert=None, down=None):
    """The worker's thread: a round every INTERVAL, the profile read again
    each time. Nothing configured: it writes an empty list, so a check you
    took out stops showing at once."""
    ck = Checker(alert, down)
    while True:
        t0 = time.time()
        try:
            ck.round(specs(deckconf.load()[0]))
        except Exception as e:
            import dlog
            dlog.event_throttled("CHECKS", "round-failed", str(e)[:60])
        time.sleep(max(1, INTERVAL - (time.time() - t0)))

def start(alert=None, down=None):
    threading.Thread(target=runner, args=(alert, down), daemon=True).start()
