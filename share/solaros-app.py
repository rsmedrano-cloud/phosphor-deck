"""Phosphor on a SolarOS panel: a menu of the deck. MicroPython.

The brain hands this file out with its address and token already in URL
(`phosphor solaros on` prints the two lines and copies them):

    curl -o /phosphor.py "http://BRAIN:8484/solaros.py?token=TOKEN"
    python /phosphor.py

What it reads comes over HTTP: the glance (the fleet's light, mentions,
todos), drawn here and repainted only when it changes (an e-ink panel
flashes on every repaint), and the menu's entries. Everything that does
something -- an assistant's tab, notes, a note, the fleet's upgrades --
opens an ssh session with this panel's own key, which the brain lets in
once (`pair with the brain` here, `phosphor solaros pair` there, the same
fingerprint on both). The token crosses the LAN in the clear; it can read,
never type.

Up, Down (the wheel) and Enter; r reads the brain again; Esc, q or EXIT
leave a screen.
"""
import sys, json
import solaros
from solaros import tui

URL = ""            # filled in by the brain when it serves this file
EVERY = 30          # seconds between reads while a screen sits there
WORDS = {"green": "all clear", "amber": "worth a look", "red": "ATTENTION", "unknown": "no data"}
LAUNCHER = "/launcher.json"
ICON = "dashboard"


# -- the brain, over HTTP ---------------------------------------------

def at(url, path):
    """url's origin with path, the token kept: .../glance?token=T -> .../menu?token=T"""
    parts = url.split("?", 1)              # no str.partition in every MicroPython build
    head, query = parts[0], parts[1] if len(parts) > 1 else ""
    cut = head.find("/", 8)
    origin = head[:cut] if cut > 0 else head
    return origin + path + ("?" + query if query else "")


def call(url, path, body=None):
    """(answer, None) or (None, why): GET, or POST with a JSON body."""
    try:
        if body is None:
            r = solaros.http.get(at(url, path), None, 8000, 16384)
        else:
            r = solaros.http.post(at(url, path), json.dumps(body),
                                  {"Content-Type": "application/json"}, 8000, 16384)
    except OSError as e:
        return None, "no answer from the brain (%s)" % e
    if r["status_code"] == 401:
        return None, "token refused: fetch /phosphor.py again"
    if r["status_code"] != 200 or r["truncated"]:
        return None, "the brain answered %d" % r["status_code"]
    try:
        return json.loads(r["body"].decode()), None
    except ValueError:
        return None, "the brain sent something that isn't JSON"


# -- this panel's ssh key ---------------------------------------------

def fingerprint(key):
    """SHA256:... the way ssh-keygen -l and the brain print it."""
    try:
        import binascii, hashlib
        raw = binascii.a2b_base64(key.split()[1])
        return "SHA256:" + binascii.b2a_base64(hashlib.sha256(raw).digest()).decode().strip().rstrip("=")
    except Exception:
        return "?"


def my_key(make=False):
    """This panel's public key line, or None (none yet, and make is False)."""
    k = solaros.ssh_keys
    if not k.default_exists():
        if not make:
            return None
        k.generate()
    return k.public_key()


# -- drawing ----------------------------------------------------------

class Screen:
    """Draws whole frames but sends only the lines that changed."""
    def __init__(self):
        self.shown = None

    def draw(self, body, foot, force=False):
        rows, cols = tui.size()
        lines = [(t[:cols], a) for t, a in body[:rows - 1]]
        lines += [("", 0)] * (rows - 1 - len(lines)) + [(foot[:cols], 0)]
        if lines == self.shown and not force:
            return
        if self.shown is None or force or len(self.shown) != len(lines):
            tui.clear()
            for i, (t, a) in enumerate(lines):
                if t:
                    tui.addstr(i, 0, t, a or tui.NORMAL)
        else:
            for i, (t, a) in enumerate(lines):
                if self.shown[i] != (t, a):
                    tui.addstr(i, 0, t + " " * (cols - len(t)), a or tui.NORMAL)
        tui.refresh()
        self.shown = lines


def key(seconds):
    """A key within seconds: 'up', 'down', 'enter', 'r', 'quit', or None."""
    left = seconds * 1000
    while left > 0 and not solaros.should_exit():
        k = tui.getch(500)
        left -= 500
        if k is None:
            continue
        if k == getattr(tui, "KEY_UP", None) or k == ord("k"):
            return "up"
        if k == getattr(tui, "KEY_DOWN", None) or k == ord("j") or k == 9:
            return "down"
        if k in (10, 13, ord(" ")):
            return "enter"
        if k == ord("r"):
            return "r"
        if k in (27, ord("q"), getattr(tui, "KEY_ESCAPE", 27)):
            return "quit"
    return "quit" if solaros.should_exit() else None


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def headline(p, why):
    if p is None:
        return [("PHOSPHOR", tui.BOLD), (why or "waiting for the brain...", tui.BOLD)]
    status = p.get("status", "unknown")
    out = [("PHOSPHOR  " + WORDS.get(status, status), tui.INVERSE if status == "red" else tui.BOLD)]
    if why:
        out.append(("! " + why, tui.BOLD))
    return out


def summary(p):
    """One line: the fleet, mentions, todos."""
    f = p.get("fleet", {})
    total = f.get("total", 0)
    bits = ["fleet %d/%d" % (f.get("ok", 0), total) if total else "fleet: no data"]
    if p.get("mentions"):
        bits.append(plural(p["mentions"], "mention"))
    if p.get("todos"):
        bits.append(plural(p["todos"], "todo"))
    return " · ".join(bits)


def glance_lines(p, why, rows):
    out = headline(p, why)
    if p is None:
        return out
    out.append(("", 0))
    f = p.get("fleet", {})
    total = f.get("total", 0)
    if not total:
        out.append(("fleet: no data", 0))
    elif f.get("stale"):
        out.append(("fleet: readings stopped", tui.BOLD))
    elif not f.get("problems"):
        out.append(("fleet: all %d hosts ok" % total, 0))
    else:
        out.append(("fleet: %d/%d ok" % (f.get("ok", 0), total), tui.BOLD))
    room = max(0, rows - 1 - len(out) - 4)      # keep the three counts and a gap
    for pr in f.get("problems", [])[:room]:
        out.append(("  %s %s: %s" % ("x" if pr.get("down") else "-", pr.get("host", "?"),
                                      pr.get("detail", "")),
                    tui.BOLD if pr.get("down") else 0))
    out.append(("", 0))
    n = p.get("mentions", 0)
    out.append(("mentions: " + ("%d unread" % n if n else "nothing unread"), tui.BOLD if n else 0))
    n = p.get("todos", 0)
    out.append(("todos: " + (plural(n, "open todo") if n else "nothing pending"), 0))
    n = p.get("workspaces", 0)
    out.append(("workspaces: " + (plural(n, "to push or commit") if n else "all clean"), 0))
    return out


# -- screens ----------------------------------------------------------

def glance(url, scr):
    """The glance: what's wrong, at a look. Enter or r reads again."""
    last, why = None, None
    while not solaros.should_exit():
        p, why = call(url, "/glance")
        if p is not None:
            last = p
        rows, _ = tui.size()
        scr.draw(glance_lines(last, why, rows), "Enter reads again · Esc back")
        k = key(EVERY)
        while k in ("up", "down"):
            k = key(EVERY)
        if k == "quit":
            return


def message(scr, lines, foot="Enter or Esc back"):
    scr.draw([(t, a) for t, a in lines], foot)
    while key(3600) not in ("enter", "quit") and not solaros.should_exit():
        pass


def pair(url, scr):
    """This panel's key to the brain; the brain's Enter lets it in."""
    k = my_key()
    if k is None:
        scr.draw([("PAIR", tui.BOLD), ("", 0), ("making this panel's ssh key:", 0),
                  ("once, and it can take a minute", 0)], "")
        try:
            k = my_key(make=True)
        except OSError as e:
            return message(scr, [("PAIR", tui.BOLD), ("", 0), ("no ssh key: %s" % e, tui.BOLD)])
    fp = fingerprint(k)
    while not solaros.should_exit():
        a, why = call(url, "/pair", {"key": k})
        state = (a or {}).get("state")
        if state == "paired":
            message(scr, [("PAIR", tui.BOLD), ("", 0), ("paired: the brain lets this panel in", 0),
                          ("", 0), ("this panel: " + fp, 0)])
            return True
        if state == "pending":
            body = [("PAIR", tui.BOLD), ("", 0), ("on the brain, phosphor solaros pair", 0),
                    ("shows a fingerprint. This panel's:", 0), ("", 0), (fp, tui.BOLD), ("", 0),
                    ("the same? press Enter there.", 0)]
            scr.draw(body, "waiting for the brain · Esc back")
            if key(3) == "quit":
                return False
            continue
        lines = [("PAIR", tui.BOLD), ("", 0)]
        if state == "closed":
            lines += [("the brain isn't pairing now:", 0), ("run  phosphor solaros pair  there,", tui.BOLD),
                      ("then Enter here.", 0)]
        else:
            lines += [((a or {}).get("why") or why or "the brain said no", tui.BOLD)]
        lines += [("", 0), ("this panel: " + fp, 0)]
        scr.draw(lines, "Enter tries again · Esc back")
        if key(3600) != "enter":
            return False
    return False


def launcher_state():
    """'there', 'room' (it can go in), or None (no launcher file, or full)."""
    st = getattr(solaros, "storage", None)
    if st is None or not st.exists(LAUNCHER):
        return None
    try:
        conf = json.loads(st.read_file(LAUNCHER, 16384).decode())
    except Exception:
        return None
    items = conf.get("items", [])
    if any("phosphor.py" in (i.get("command") or "") for i in items):
        return "there"
    return "room" if free_cell(conf) else None


def free_cell(conf):
    lay = conf.get("layout", {})
    taken = [(i.get("column"), i.get("row")) for i in conf.get("items", [])]
    if len(taken) >= 32:
        return None
    for r in range(lay.get("rows", 1)):
        for c in range(lay.get("columns", 1)):
            if (c, r) not in taken:
                return c, r
    return None


def add_to_launcher(scr):
    st = solaros.storage
    try:
        conf = json.loads(st.read_file(LAUNCHER, 16384).decode())
        c, r = free_cell(conf)
        conf.setdefault("items", []).append({"name": "Phosphor", "icon": ICON,
                                             "command": "python /phosphor.py", "column": c, "row": r})
        st.write_file(LAUNCHER, json.dumps(conf))
        done = "Phosphor is in the launcher now"
    except Exception as e:
        done = "couldn't change %s: %s" % (LAUNCHER, e)
    message(scr, [("LAUNCHER", tui.BOLD), ("", 0), (done, 0)])


def open_over_ssh(url, scr, entry, ssh):
    """Tell the brain which entry, then hand the screen to SolarOS's ssh:
    the brain's session starts there. Comes back only if that failed."""
    a, why = call(url, "/open", {"open": entry["id"]})
    if not a or not a.get("ok"):
        return message(scr, [(entry["label"], tui.BOLD), ("", 0), (why or (a or {}).get("why") or "refused", tui.BOLD)])
    try:
        solaros.apps.launch("ssh", [ssh])
    except Exception as e:
        message(scr, [(entry["label"], tui.BOLD), ("", 0), ("ssh didn't start: %s" % e, tui.BOLD)])


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    if not url:
        solaros.write("usage: python /phosphor.py URL\n"
                      "  (phosphor solaros on, on the brain, prints it)\n")
        return
    if not hasattr(solaros, "http"):
        solaros.write("this SolarOS build has no HTTP client (network.http-client)\n")
        return
    scr, sel, p, why, menu = Screen(), 0, None, None, None
    paired, fresh = None, True
    while not solaros.should_exit():
        if fresh:
            got, why = call(url, "/glance")
            p = got if got is not None else p
            m, _ = call(url, "/menu")
            menu = m if m is not None else menu
            if paired is None and my_key() is not None:
                a, _ = call(url, "/pair", {"key": my_key()})
                paired = (a or {}).get("state") == "paired" if a else None
            fresh = False
        items = []
        for e in (menu or {}).get("entries", []):
            items.append(("glance", e) if e["id"] == "glance" else ("ssh", e))
        if not paired:
            items.append(("pair", {"label": "pair with the brain"}))
        if launcher_state() == "room":
            items.append(("launcher", {"label": "put Phosphor in the launcher"}))
        sel = min(sel, max(0, len(items) - 1))
        rows, _ = tui.size()
        body = headline(p, why) + ([(summary(p), 0)] if p else []) + [("", 0)]
        room = max(1, rows - 1 - len(body))
        top = max(0, sel - room + 1)
        for i, (kind, e) in enumerate(items[top:top + room], top):
            label = e["label"] + ("  (pair first)" if kind == "ssh" and not paired else "")
            body.append(("> " + label if i == sel else "  " + label, tui.INVERSE if i == sel else 0))
        scr.draw(body, "Enter opens · r reads again · Esc leaves")
        k = key(EVERY)
        if k is None or k == "r":
            fresh = True
        elif k == "quit":
            break
        elif k == "up" and items:
            sel = (sel - 1) % len(items)
        elif k == "down" and items:
            sel = (sel + 1) % len(items)
        elif k == "enter" and items:
            kind, e = items[sel]
            if kind == "glance":
                glance(url, scr)
            elif kind == "pair":
                paired = pair(url, scr) or paired
            elif kind == "launcher":
                add_to_launcher(scr)
            elif not paired:
                paired = pair(url, scr) or paired
            else:
                open_over_ssh(url, scr, e, menu.get("ssh"))
            scr.shown, fresh = None, True
    tui.clear()
    tui.refresh()


main()
