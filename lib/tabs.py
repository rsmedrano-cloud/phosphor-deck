"""phosphor tabs - the tabs your profile brings back after every restart.

A tab kept in the profile (from +, keep, a workspace, a layout) comes back
each time the deck starts, even after you closed it. Here you see them all,
which ones are open now, and choose what stays:

    phosphor tabs          f forget one (out of the profile, after a y/n),
                           J / K move it, o open a closed one again; by key or tap
    phosphor tabs --list   the same, printed
    phosphor tabs --forget NAME   the same forget, without the picker
    phosphor tabs --closing       is this pane a kept tab's last program? (read-only)

Closing a tab's last program also offers "f close and forget": phosphor run
calls closing()/forget() (this file's own functions) directly, in-process;
its optional Rust rewrite in rust/run has no Python to import, so it shells
out to these same two flags instead of reimplementing the profile edit.
Forgetting edits the profile as text (comments stay) and keeps deck.toml.bak.
"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, tui

PHOSPHOR = os.path.join(REPO, "phosphor")
INV = "\x1b[7m"

# ── the profile as text ───────────────────────────────────────
def spans(text):
    """[(name, first line, line after its content)] of every [[tabs]] block.
    A block ends at its last line with content: comments and blank lines
    before the next section belong to what follows."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        if lines[i].strip() != "[[tabs]]":
            i += 1; continue
        j = i + 1
        while j < len(lines) and not lines[j].lstrip().startswith("["):
            j += 1
        end = j
        while end > i + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        m = re.search(r'^\s*name\s*=\s*"([^"]*)"', "\n".join(lines[i:end]), re.M)
        out.append((m.group(1) if m else "", i, end))
        i = j
    return out

def remove_text(text, name):
    lines = text.split("\n")
    for n, i, end in spans(text):
        if n == name:
            if end < len(lines) and not lines[end].strip():
                end += 1                     # and the blank line after it
            return "\n".join(lines[:i] + lines[end:])
    return text

def move_text(text, name, step):
    """Swap the tab with its neighbour (step -1 up, +1 down)."""
    sp = spans(text)
    k = next((x for x, s in enumerate(sp) if s[0] == name), None)
    o = None if k is None else k + step
    if k is None or not 0 <= o < len(sp):
        return text
    lines = text.split("\n")
    (a, ai, ae), (b, bi, be) = sorted([sp[k], sp[o]], key=lambda s: s[1])
    first, second = lines[ai:ae], lines[bi:be]
    return "\n".join(lines[:ai] + second + lines[ae:bi] + first + lines[be:])

def write(new, check, expect=None):
    """Only a profile that parses and passes check; then gen, quietly."""
    p = deckconf.path()
    if deckconf.example():
        return "there's no profile yet: phosphor init"
    err = deckconf.write_profile(new, check, expect=expect, p=p)
    if err:
        return err + ("" if "nothing written" in err else ": nothing written")
    subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None

def from_tabs_d(name):
    """Which tabs.d file this tab's name comes from, if any."""
    return deckconf.tabs_d_names().get(name)

def pinned(name, prof=None):
    """Does the profile hold a stub -- name only, no content -- placing
    this tabs.d tab somewhere on purpose?"""
    prof = prof if prof is not None else (deckconf.load()[0] or {})
    return name in deckconf.pinned_tabs_d(prof)

def pin_unplaced(text):
    """Turn every not-yet-placed tabs.d tab into a stub -- name only -- at
    the end, in the same order they'd fall back to. Moving one for the
    first time needs this: without it, it'd swap past its real neighbours,
    which are only implicit until they're written down too."""
    have = {t.get("name") for t in deckconf.tomllib.loads(text).get("tabs", [])}
    missing = [t.get("name") for t, _ in deckconf.tabs_d() if t.get("name") not in have]
    if not missing:
        return text
    return text.rstrip("\n") + "\n" + "".join('\n[[tabs]]\nname = "%s"\n' % n for n in missing)

def forget(name):
    """Out of the profile: it won't come back after a restart -- or, for a
    tabs.d tab you'd placed, just unplaced (it still comes back, at the
    end). None, or why not."""
    text = open(deckconf.path()).read()
    if not any(n == name for n, _, _ in spans(text)):
        if from_tabs_d(name):
            return "not placed anywhere: already at the end, in file-name order"
        return "%s isn't in your profile" % name
    return write(remove_text(text, name), lambda p: all(t.get("name") != name for t in p.get("tabs", [])), text)

def move(name, step):
    text = disk = open(deckconf.path()).read()
    have = [n for n, _, _ in spans(text)]
    if name not in have and not from_tabs_d(name):
        return "%s isn't in your profile" % name
    if name not in have or not 0 <= have.index(name) + step < len(have):
        text = pin_unplaced(text)        # past the end: tabs.d's come next
    new = move_text(text, name, step)
    if new == text: return None
    want = [t.get("name") for t in deckconf.tomllib.loads(text).get("tabs", [])]
    k = want.index(name); want[k], want[k + step] = want[k + step], want[k]
    return write(new, lambda p: [t.get("name") for t in p.get("tabs", [])] == want, disk)

# ── the deck ──────────────────────────────────────────────────
def bare(name):
    """A tab's name without what the deck adds to it (✎ while editing, ● unseen)."""
    return re.sub(r"\s*[✎●]\d*.*$", "", name or "").strip()

def zj(*a):
    import newtab
    return newtab.zj(*a)

def open_now():
    """{bare tab name} open in the session, when inside the deck."""
    if not os.environ.get("ZELLIJ"): return None
    try:
        return {bare(t.get("name")) for t in json.loads(zj("list-tabs", "-j") or "[]")}
    except ValueError:
        return None

def mine():
    """(my tab's bare name, how many panes it has) for the pane this runs in."""
    try:
        ps = json.loads(zj("list-panes", "-a", "-j") or "[]")
    except ValueError:
        return None, 0
    me = int(os.environ.get("ZELLIJ_PANE_ID", "-1"))
    p = next((p for p in ps if not p["is_plugin"] and p["id"] == me), None)
    if not p: return None, 0
    n = sum(1 for q in ps if not q["is_plugin"] and q["tab_id"] == p["tab_id"] and not q["is_suppressed"])
    return bare(p["tab_name"]), n

def kept(name):
    """Does it come back after a restart? Its own profile entry, or tabs.d."""
    prof, _ = deckconf.load()
    return any(t.get("name") == name for t in (prof or {}).get("tabs", [])) or bool(from_tabs_d(name))

def reopen(name):
    lay = os.path.expanduser("~/.config/zellij/layouts/tab-%s.kdl" % name.lower())
    if not os.path.exists(lay): return "no layout for %s: phosphor gen" % name
    zj("new-tab", "--layout", lay, "--name", name)
    return None

def all_tabs(prof):
    """The profile's own tabs, plus tabs.d's (a name the profile already
    has wins), same order gen builds them in."""
    own = (prof or {}).get("tabs", [])
    have = {t["name"] for t in own}
    return own + [{"name": n} for n in deckconf.tabs_d_names() if n not in have]

class Panel(tui.ListPanel):
    """Every kept tab, open or closed now; f forgets (or un-places a
    tabs.d tab) after a y/n, J / K move it, o opens a closed one again."""
    KEYS = [("f", "forget"), ("K", "left"), ("J", "right"), ("o", "open"), ("q", "quit")]

    def fetch(self):
        prof, _ = deckconf.load()
        d, live = deckconf.tabs_d_names(), open_now()
        return [(t["name"], None if live is None else t["name"] in live,
                 os.path.basename(d[t["name"]]) if t["name"] in d else "",
                 t["name"] in d and pinned(t["name"], prof)) for t in all_tabs(prof)]

    def header(self, w):
        shut = sum(1 for _, o, _, _ in self.rows if o is False)
        return topbar("TABS", "what your profile brings back",
                      "%d%s" % (len(self.rows), " · %d closed now" % shut if shut else ""), w)

    def lines(self, w, sel):
        if not self.rows:
            return [" " + DIM + "no tabs kept: + in the deck adds one" + RST]
        nw = max([len(n) for n, _, _, _ in self.rows] + [8])
        out = []
        for i, (n, o, f, _) in enumerate(self.rows):
            now = "" if o is None else ("open" if o else "closed now")
            src = "tabs.d/" + f if f else ""
            if i == sel:
                out.append(" " + INV + pad(" %-*s  %-11s %s" % (nw, n, now, src), w - 2)[:w - 2] + RST)
            else:
                out.append("  " + FG + "%-*s" % (nw, n) + RST + "  " + (AMB if o is False else FG)
                           + "%-11s" % now + RST + " " + DIM + src + RST)
        return out

    def act(self, k, row):
        n, o, f, placed = row
        if k == "f":
            if f and not placed:
                return self.say("%s comes from tabs.d and isn't placed: it's already at the end" % n)
            if f:
                return self.confirm("un-place %s? it stays in tabs.d, at the end" % n,
                                    lambda: self.done(forget(n), "%s un-placed" % n))
            self.confirm("forget %s? it won't come back after a restart" % n,
                         lambda: self.done(forget(n), "%s forgotten" % n), note="deck.toml.bak keeps a copy")
        elif k in ("K", "J"):
            step = -1 if k == "K" else 1
            if not 0 <= self.sel + step < len(self.rows):
                return self.say("%s is already the %s one" % (n, "first" if step < 0 else "last"), DIM)
            self.say("moving %s..." % n, DIM); self.draw()
            err = move(n, step)
            if err:
                return self.say("✗ " + err, RED)
            self.sel += step
            self.say("✓ %s moved: in place after a restart" % n, PH)
            self.refresh()
        elif k == "o":
            if o is None:
                return self.say("open it from inside the deck")
            if o:
                return self.say("%s is open already" % n, DIM)
            err = reopen(n)
            self.say("✗ " + err if err else "✓ %s opened" % n, RED if err else PH)
            self.refresh()

    def done(self, err, ok):
        return (False, err) if err else (True, ok)

def main():
    argv = sys.argv[1:]
    prof, _ = deckconf.load()
    d = deckconf.tabs_d_names()
    def note(name, live):
        base = "" if live is None else ("open" if name in live else "closed now")
        tag = "tabs.d/" + os.path.basename(d[name]) if name in d else ""
        return " · ".join(x for x in (base, tag) if x)
    if "--forget" in argv:
        i = argv.index("--forget")
        name = argv[i + 1] if i + 1 < len(argv) else ""
        if not name:
            print("usage: phosphor tabs --forget NAME"); return 2
        err = forget(name)
        if err:
            print(err); return 1
        print("%s forgotten" % name); return 0
    if "--closing" in argv:
        # phosphor run's own "is this pane a kept tab's last program?" --
        # prints the tab's name if so, nothing otherwise. Read-only.
        if os.environ.get("ZELLIJ"):
            tab, panes = mine()
            if tab and panes == 1 and kept(tab):
                print(tab)
        return 0
    if "--list" in argv or not sys.stdin.isatty():
        live = open_now()
        for t in all_tabs(prof):
            print("%-16s %s" % (t["name"], note(t["name"], live)))
        return 0
    return Panel().run()

if __name__ == "__main__":
    sys.exit(main() or 0)
