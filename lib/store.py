#!/usr/bin/env python3
"""phosphor store - a catalog of TUIs, installed from their GitHub releases
into ~/.local/bin. No sudo. Your own apps (apps.toml) are listed first as
"yours"; Enter on anything installed opens it in a new tab."""
import json, os, re, select, shutil, subprocess, sys, tarfile, tempfile, termios, tty, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, BLOOM, AMB, RED, RULE, RST, share, vlen, pad
from ui import getkey as ui_getkey
import apps as mine

HOME    = os.path.expanduser("~")
BIN     = os.path.join(HOME, ".local/bin")
CATALOG = None  # resolved in main()
API     = "https://api.github.com/repos/%s/releases/latest"
INV     = "\x1b[7m"

def binname(a): return a.get("b", a["n"])
def where(a): return mine.have(mine.exe(a))

def installed(a):
    act = a.get("action")
    if act == "glados":
        import tts
        return tts.is_glados_ready()[0]
    if act == "models":
        import tts
        return tts.has_models()
    return where(a) is not None

def used_by_deck(path):
    """Never remove something a deck layout launches."""
    d = os.path.join(HOME, ".config/zellij/layouts")
    try:
        return any(path in open(os.path.join(d, f)).read() for f in os.listdir(d) if f.endswith(".kdl"))
    except OSError:
        return False

def remove(a, ask):
    """Only what lives in ~/.local/bin (what Phosphor installed); ask first."""
    if a.get("yours"):
        return AMB + a["n"] + " is yours: take it out of " + mine.path().replace(HOME, "~", 1) + RST
    act = a.get("action")
    if act == "glados":
        import tts
        if not tts.is_glados_ready()[0]:
            return DIM + a["n"] + " isn't installed" + RST
        if not ask("remove GLaDOS-TTS models from ~/.local/share/phosphor? (y/N) "):
            return DIM + "kept " + a["n"] + RST
        tts.remove_glados()
        return PH + "✓ removed " + a["n"] + RST
    if act == "models":
        import tts
        if not tts.has_models():
            return DIM + a["n"] + " isn't installed" + RST
        if not ask("remove extra voice models from ~/.local/share/phosphor? (y/N) "):
            return DIM + "kept " + a["n"] + RST
        tts.remove_models()
        return PH + "✓ removed " + a["n"] + RST
    p = where(a)
    if not p:
        return DIM + a["n"] + " isn't installed" + RST
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(BIN) and os.path.dirname(p) != BIN:
        return AMB + a["n"] + " comes from your system (" + p + "): remove it with your package manager" + RST
    if used_by_deck(p):
        return AMB + "the deck uses " + a["n"] + ": not removing it" + RST
    if not ask("remove " + a["n"] + " from ~/.local/bin? (y/N) "):
        return DIM + "kept " + a["n"] + RST
    os.remove(p)
    return PH + "✓ removed " + a["n"] + RST

def fetch_asset(app):
    req = urllib.request.Request(API % app["r"], headers={"User-Agent": "phosphor-store"})
    with urllib.request.urlopen(req, timeout=25) as r:
        rel = json.load(r)
    pat = re.compile(app["m"])
    for a in rel.get("assets", []):
        if pat.search(a["name"]):
            return a["browser_download_url"], a["name"], rel.get("tag_name", "")
    raise RuntimeError("no release asset matches /%s/" % app["m"])

def install(app, say):
    act = app.get("action")
    if act == "glados":
        say(AMB + "installing GLaDOS-TTS and neural models..." + RST)
        import tts
        res_code = tts.install_glados()
        if res_code != 0: raise RuntimeError("GLaDOS installation failed")
        return "ready"
    if act == "models":
        say(AMB + "downloading neural voice models..." + RST)
        import tts
        res_code = tts.install_models()
        if res_code != 0: raise RuntimeError("voice models download failed")
        return "ready"
    if app["n"] == "piper":
        say(AMB + "installing Piper neural TTS engine..." + RST)
        import tts
        res_code = tts.install_piper()
        if res_code != 0: raise RuntimeError("Piper installation failed")
        return "ready"
    say(AMB + "looking up " + app["n"] + "'s release..." + RST)
    url, name, tag = fetch_asset(app)
    say(AMB + "downloading " + name + " (" + tag + ")..." + RST)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, name)
        req = urllib.request.Request(url, headers={"User-Agent": "phosphor-store"})
        with urllib.request.urlopen(req, timeout=120) as r, open(p, "wb") as f:
            shutil.copyfileobj(r, f)
        say(AMB + "extracting..." + RST)
        out = os.path.join(td, "x"); os.makedirs(out, exist_ok=True)
        if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
            with tarfile.open(p) as t: t.extractall(out)
        elif name.endswith(".zip"):
            with zipfile.ZipFile(p) as z: z.extractall(out)
        else:
            shutil.copy(p, os.path.join(out, binname(app)))
        target = binname(app)
        found = None
        for root, _, files in os.walk(out):
            for f in files:
                fp = os.path.join(root, f)
                if f == target or f == app["n"]:
                    found = fp; break
            if found: break
        if not found:  # otherwise: the package's only big executable
            cands = [os.path.join(r, f) for r, _, fs in os.walk(out) for f in fs
                     if not f.endswith((".md", ".txt", ".1", ".json", ".toml", ".fish", ".zsh", ".bash"))]
            cands = [c for c in cands if os.path.getsize(c) > 100000]
            if len(cands) >= 1: found = max(cands, key=os.path.getsize)
        if not found: raise RuntimeError("couldn't find the binary inside the package")
        dst = os.path.join(BIN, target)
        shutil.copy(found, dst); os.chmod(dst, 0o755)
    return tag

def getkey():
    """Keys, plus WUP/WDN for the mouse wheel and touch scrolling."""
    k = ui_getkey(None)
    if isinstance(k, tuple):
        return {64: "WUP", 65: "WDN"}.get(k[1]) if k[4] else None
    return k

def catalog():
    """Yours first, then the catalog by category. Plus a problem with apps.toml, if any."""
    own, problem = mine.yours()
    names = {a["n"] for a in own}
    rest = sorted((a for a in json.load(open(CATALOG)) if a["n"] not in names), key=lambda a: (a["c"], a["n"]))
    return own + rest, problem

def dump():
    """No TTY: plain listing and exit."""
    apps, problem = catalog()
    if problem: print(problem)
    for a in apps:
        print("%s %-14s %-9s %s" % ("*" if installed(a) else " ", a["n"], a["c"], a["d"]))

def main():
    global CATALOG
    CATALOG = share("store.json")

    if not sys.stdin.isatty():
        dump(); return 0
    apps, msg = catalog()
    msg = (AMB + msg + RST) if msg else ""
    sel, top, filt, only = 0, 0, "", False
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((90, 30))
            w = min(cols, 110)
            have = {a["n"]: installed(a) for a in apps}     # one look per redraw
            view = [a for a in apps if (not filt or filt.lower() in (a["n"] + a["c"] + a["d"]).lower())
                    and (not only or have[a["n"]])]
            sel = max(0, min(sel, len(view) - 1)) if view else 0
            body = max(5, rows - 6)
            if sel < top: top = sel
            if sel >= top + body: top = sel - body + 1
            ni = sum(1 for a in apps if have[a["n"]])
            head = "─ PHOSPHOR STORE " + ("· installed " if only else "")
            tail = "─ %d apps · %d installed ─" % (len(apps), ni)
            out = [RULE + "╭" + head + "─" * max(0, w - 2 - len(head) - len(tail)) + tail + "╮" + RST]
            lastc = None
            shown = view[top:top + body]
            for i, a in enumerate(shown):
                idx = top + i
                if a["c"] != lastc:
                    lastc = a["c"]
                    out.append(RULE + "│" + RST + " " + pad(MUTE + a["c"].upper() + RST, w - 3) + RULE + "│" + RST)
                mark = "●" if have[a["n"]] else "○"
                nw = min(14, max(8, w - 8))
                nm = ("%-*.*s" % (nw, nw, a["n"]))
                room = w - 6 - nw               # what's left for the description
                if room >= 12:
                    d = a["d"]
                    desc = d if len(d) <= room else d[:room - 1].rsplit(" ", 1)[0] + "…"
                else:
                    desc = ""                    # narrow pane: names only
                if idx == sel:
                    line = INV + " " + mark + " " + nm + (" " + desc if desc else "") + RST
                else:
                    line = (" " + (PH if have[a["n"]] else DIM) + mark + RST + " "
                            + FG + nm + RST + (" " + DIM + desc + RST if desc else ""))
                out.append(RULE + "│" + RST + pad(line, w - 2) + RULE + "│" + RST)
            while len(out) - 1 < body:
                out.append(RULE + "│" + RST + " " * (w - 2) + RULE + "│" + RST)
            out.append(RULE + "╰" + "─" * (w - 2) + "╯" + RST)
            hint = (" j/k move · enter " + ("open in a tab" if view and have[view[sel]["n"]] else "install")
                    + " · i " + ("all" if only else "installed") + " · d remove · / filter · q quit")
            if filt: hint = " filter: " + AMB + filt + RST + DIM + "  (esc clears)" + RST
            out.append(DIM + hint + RST)
            if msg: out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"); sys.stdout.flush()

            k = getkey()
            msg = ""
            if k in ("q", "\x03"): break
            elif k in ("j", "\x1b[B"): sel += 1
            elif k in ("k", "\x1b[A"): sel -= 1
            elif k == "WDN": sel += 3
            elif k == "WUP": sel -= 3
            elif k == "g": sel = 0
            elif k == "G": sel = len(view) - 1
            elif k == "/":
                sys.stdout.write("\x1b[?1049l\x1b[?25h"); termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, termios.tcgetattr(sys.stdin.fileno()))
                sys.stdout.write("\x1b[%d;1H\x1b[K filter: " % (rows - 1)); sys.stdout.flush()
                filt = sys.stdin.readline().strip(); sys.stdout.write("\x1b[?25l"); sel = 0; top = 0
            elif k == "\x1b": filt = ""; only = False; sel = 0; top = 0
            elif k == "i": only = not only; sel = 0; top = 0
            elif k == "d" and view:
                def ask(q):
                    sys.stdout.write("\x1b[%d;1H\x1b[K " % rows + AMB + q + RST); sys.stdout.flush()
                    return getkey() in ("y", "Y")
                msg = remove(view[sel], ask)
            elif k in ("\r", "\n"):
                if view:
                    a = view[sel]
                    if have[a["n"]]:
                        if a.get("action"):
                            msg = PH + "✓ " + a["n"] + " is installed and ready for notifications" + RST
                        else:
                            ok, m = mine.open_tab(a)
                            msg = (PH + "✓ " if ok else AMB) + m + RST
                    elif a.get("yours"):
                        msg = AMB + mine.exe(a) + " isn't installed: fix its cmd in " \
                              + mine.path().replace(HOME, "~", 1) + RST
                    else:
                        def say(m):
                            sys.stdout.write("\x1b[%d;1H\x1b[K %s" % (rows, m)); sys.stdout.flush()
                        try:
                            tag = install(a, say)
                            msg = PH + "✓ " + a["n"] + " " + tag + (" installed" if a.get("action") else " installed in ~/.local/bin") + RST
                        except Exception as e:
                            import dlog
                            dlog.event("STORE", "install-failed", "%s: %s" % (a["n"], e))
                            msg = RED + "✗ " + a["n"] + ": " + str(e)[:70] + RST
            sel = max(0, min(sel, max(0, len(view) - 1)))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\n")

if __name__ == "__main__":
    main()
