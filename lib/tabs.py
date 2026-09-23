"""phosphor tabs - the tabs your profile brings back after every restart.

A tab kept in the profile (from +, keep, a workspace, a layout) comes back
each time the deck starts, even after you closed it. Here you see them all,
which ones are open now, and choose what stays:

    phosphor tabs          f forget one (out of the profile), J / K move it,
                           o open a closed one again; by key or tap
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
import deckconf

PHOSPHOR = os.path.join(REPO, "phosphor")

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

def write(new, check):
    """Only a profile that parses and passes check; then gen, quietly."""
    p = deckconf.path()
    if deckconf.example():
        return "there's no profile yet: phosphor init"
    try:
        prof = deckconf.tomllib.loads(new)
    except Exception as e:
        return "the profile wouldn't parse: %s" % str(e)[:50]
    if not check(prof):
        return "the result didn't look right: nothing written"
    old = open(p).read()
    open(p + ".bak", "w").write(old)
    open(p, "w").write(new)
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
    return write(remove_text(text, name), lambda p: all(t.get("name") != name for t in p.get("tabs", [])))

def move(name, step):
    text = open(deckconf.path()).read()
    if not any(n == name for n, _, _ in spans(text)):
        if not from_tabs_d(name):
            return "%s isn't in your profile" % name
        text = pin_unplaced(text)
    new = move_text(text, name, step)
    if new == text: return None
    want = [t.get("name") for t in deckconf.tomllib.loads(text).get("tabs", [])]
    k = want.index(name); want[k], want[k + step] = want[k + step], want[k]
    return write(new, lambda p: [t.get("name") for t in p.get("tabs", [])] == want)

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
    import edit
    msg = ""
    while True:
        prof, _ = deckconf.load()
        d = deckconf.tabs_d_names()
        live = open_now()
        items = [(t["name"], note(t["name"], live), t["name"]) for t in all_tabs(prof)]
        title = "tabs your profile brings back" + ("  ·  " + msg if msg else "")
        it = edit.pick(title, items)
        msg = ""
        if not it: return 0
        name = it[2]
        if name in d:
            acts = [("K", "move it left"), ("J", "move it right")]
            if pinned(name, prof):
                acts.append(("f", "un-place it: back to the end, in file-name order"))
        else:
            acts = [("f", "forget it: out of the profile, not back after a restart"),
                    ("K", "move it left"), ("J", "move it right")]
        if live is not None and name not in live:
            acts.append(("o", "open it again now"))
        what = edit.pick(name, [], acts)
        if what == "f":
            was_pinned = name in d and pinned(name, prof)
            q = ("un-place %s? it stays in tabs.d, at the end" if was_pinned
                 else "forget %s? (deck.toml.bak keeps a copy)") % name
            sure = edit.pick(q, [], [("y", "yes"), ("n", "no")])
            if sure == "y":
                err = forget(name)
                done = "un-placed" if was_pinned else "forgotten"
                msg = (RED + err + RST) if err else (PH + "%s %s" % (name, done) + RST)
        elif what in ("K", "J"):
            err = move(name, -1 if what == "K" else 1)
            msg = (RED + err + RST) if err else (PH + "%s moved: in place after a restart" % name + RST)
        elif what == "o":
            err = reopen(name)
            msg = (RED + err + RST) if err else (PH + "%s opened" % name + RST)

if __name__ == "__main__":
    sys.exit(main() or 0)
