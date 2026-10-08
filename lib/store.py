#!/usr/bin/env python3
"""phosphor store - a catalog of TUIs, installed from their GitHub releases
into ~/.local/bin. No sudo. Your own apps (apps.toml) are listed first as
"yours"; Enter on anything installed opens it in a new tab."""
import json, os, re, shutil, sys, tarfile, tempfile, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, AMB, RED, RST, share, topbar
import apps as mine
import tui

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

def remove(a):
    """Only what lives in ~/.local/bin (what Phosphor installed). (question,
    do) when it can go, do() giving (ok, message); else (None, why not)."""
    if a.get("yours"):
        return None, a["n"] + " is yours: take it out of " + a.get("file", mine.path()).replace(HOME, "~", 1)
    act = a.get("action")
    if act in ("glados", "models"):
        import tts
        if not installed(a):
            return None, a["n"] + " isn't installed"
        def gone():
            (tts.remove_glados if act == "glados" else tts.remove_models)()
            return True, "removed " + a["n"]
        what = "GLaDOS-TTS models" if act == "glados" else "extra voice models"
        return "remove %s from ~/.local/share/phosphor?" % what, gone
    p = where(a)
    if not p:
        return None, a["n"] + " isn't installed"
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(BIN) and os.path.dirname(p) != BIN:
        return None, a["n"] + " comes from your system (" + p + "): remove it with your package manager"
    if used_by_deck(p):
        return None, "the deck uses " + a["n"] + ": not removing it"
    def gone():
        os.remove(p)
        return True, "removed " + a["n"]
    return "remove %s from ~/.local/bin?" % a["n"], gone

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

class Panel(tui.ListPanel):
    INTERVAL = 30        # a local file and a look at ~/.local/bin

    def __init__(self, problem):
        super().__init__()
        self.filt, self.only, self.have, self.all = "", False, {}, []
        if problem:
            self.say(problem)

    @property
    def KEYS(self):
        a = self.rows[self.sel] if self.rows else None
        return [("enter", "open in a tab" if a and self.have.get(a["n"]) else "install"),
                ("d", "remove"), ("i", "all" if self.only else "installed"), ("/", "filter"), ("q", "quit")]

    def fetch(self):
        self.all = catalog()[0]
        self.have = {a["n"]: installed(a) for a in self.all}
        f = self.filt.lower()
        return [a for a in self.all if (not f or f in (a["n"] + a["c"] + a["d"]).lower())
                and (not self.only or self.have[a["n"]])]

    def header(self, w):
        what = "installed only" if self.only else "TUIs, no sudo"
        if self.filt:
            what = "filter: " + self.filt + " (esc clears)"
        return topbar("STORE", what, "%d apps · %d installed" % (len(self.all), sum(self.have.values())), min(w, 110))

    def lines(self, w, sel):
        if not self.rows:
            return [" " + DIM + ("nothing matches" if self.filt else "nothing installed yet") + RST]
        w = min(w, 110)
        out, lastc = [], None
        nw = min(14, max(8, w - 8))
        room = w - 6 - nw                   # what's left for the description
        for i, a in enumerate(self.rows):
            if a["c"] != lastc:
                lastc = a["c"]
                out.append(tui.Head(" " + MUTE + a["c"].upper() + RST))
            have = self.have.get(a["n"])
            mark = "●" if have else "○"
            nm = "%-*.*s" % (nw, nw, a["n"])
            d = a["d"]
            desc = "" if room < 12 else d if len(d) <= room else d[:room - 1].rsplit(" ", 1)[0] + "…"
            if i == sel:
                out.append(INV + " " + mark + " " + nm + (" " + desc if desc else "") + RST)
            else:
                out.append(" " + (PH if have else DIM) + mark + RST + " " + FG + nm + RST
                           + (" " + DIM + desc + RST if desc else ""))
        return out

    def key(self, k):
        if self.ask:
            return super().key(k)
        if k == "\x1b" and (self.filt or self.only):
            self.filt, self.only, self.sel = "", False, 0
        elif k == "i":
            self.only, self.sel = not self.only, 0
        elif k == "/":
            f = self.line("filter:", self.filt)
            if f is None:
                return True
            self.filt, self.sel = f.strip(), 0
        else:
            return super().key(k)
        self.rows = self.fetch()
        return True

    def act(self, k, a):
        if k == "d":
            q, do = remove(a)
            return self.confirm(q, do) if q else self.say(do)
        if k != "enter":
            return
        if self.have.get(a["n"]):
            if a.get("action"):
                return self.say("✓ " + a["n"] + " is installed and ready for notifications", PH)
            ok, m = mine.open_tab(a)
            return self.say(("✓ " if ok else "") + m, PH if ok else AMB)
        if a.get("yours"):
            return self.say(mine.exe(a) + " isn't installed: fix its cmd in " + mine.path().replace(HOME, "~", 1))
        def say(m):
            self.msg = m; self.draw()
        try:
            tag = install(a, say)
            self.say("✓ " + a["n"] + " " + tag + (" installed" if a.get("action") else " installed in ~/.local/bin"), PH)
        except Exception as e:
            import dlog
            dlog.event("STORE", "install-failed", "%s: %s" % (a["n"], e))
            self.say("✗ " + a["n"] + ": " + str(e)[:70], RED)
        self.refresh()


def main():
    global CATALOG
    CATALOG = share("store.json")
    if not sys.stdin.isatty():
        dump(); return 0
    return Panel(catalog()[1]).run()

if __name__ == "__main__":
    sys.exit(main() or 0)
