"""phosphor shortcuts - the deck's keys are yours to change.

They live in [keys] in the profile, so an update never resets them. gen
writes them into zellij's config.kdl between two marker lines and touches
nothing else in that file: binds of your own go anywhere outside the markers.
A config.kdl without the markers is left alone; `phosphor shortcuts --kdl`
prints the block to paste inside its `keybinds { }`.

    phosphor shortcuts           pick an action, press its new key (or tap)
    phosphor shortcuts --kdl     the block gen would write

    [keys]
    edit    = "Alt r"      # edit this tab
    new_tab = "Alt n"      # a new tab in the pane's folder
    note    = "Alt j"      # jot a note or todo, tagged with this tab
    zoom    = "Alt z"
    leave   = "Alt x"      # Ctrl-q always leaves too
    controls = "Alt g"     # zellij's own controls
    tabs    = "Alt"        # + 1..9
    panes   = "Alt"        # + arrows
    # "" turns one off
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

# (id, what it does, default, "key" or "prefix")
ACTIONS = [
    ("edit",     "edit this tab: unlock, change, save or put back", "Alt r", "key"),
    ("new_tab",  "new tab (the + menu) in the pane's folder",       "Alt n", "key"),
    ("note",     "a note or todo from here, tagged with this tab",  "Alt j", "key"),
    ("zoom",     "zoom: the focused pane takes the whole tab",      "Alt z", "key"),
    ("leave",    "leave the deck (it keeps running)",               "Alt x", "key"),
    ("controls", "take and give back zellij's controls",            "Alt g", "key"),
    ("tabs",     "go to a tab: this + 1..9",                        "Alt",   "prefix"),
    ("panes",    "move between panes: this + arrows",               "Alt",   "prefix"),
]
PREFIXES = ["Alt", "Ctrl Alt", "Ctrl Shift", ""]

# Keys tools in the deck use themselves, to warn before taking one.
TAKEN = {
    "matterhorn": ["Alt 8", "Alt a", "Alt b", "Alt d", "Alt e", "Alt f", "Alt k", "Alt l",
                   "Alt o", "Alt p", "Alt s", "Ctrl b", "Ctrl c", "Ctrl f", "Ctrl g", "Ctrl n",
                   "Ctrl o", "Ctrl p", "Ctrl q", "Ctrl s", "Ctrl t"],
    "the shell": ["Ctrl a", "Ctrl c", "Ctrl d", "Ctrl e", "Ctrl l", "Ctrl r", "Ctrl u", "Ctrl w", "Ctrl z"],
}

BEGIN = "    // ── PHOSPHOR KEYS: phosphor gen writes from here to END PHOSPHOR KEYS, from [keys] in your profile."
NOTE  = "    // ── Binds of your own go anywhere else in this file: gen never touches them."
END   = "    // ── END PHOSPHOR KEYS"
RUN   = 'Run "sh" "-c" "exec \\"$HOME/.local/bin/phosphor\\" %s" { in_place true; close_on_exit true; name "%s"; }'

def current(prof):
    """{action: key} with the defaults for what [keys] doesn't say."""
    mine = (prof or {}).get("keys") or {}
    return {a: str(mine.get(a, d)).strip() for a, _, d, _ in ACTIONS}

def dash(key):
    """"Alt r" → "Alt-r", for people."""
    return "-".join(key.split()) if key else "off"

def expand(keys):
    """{zellij key: action} every bind takes, prefixes spelled out."""
    out = {}
    for a, _, _, kind in ACTIONS:
        k = keys.get(a, "")
        if not k: continue
        if kind == "key":
            out[k] = a
        elif a == "tabs":
            for i in range(1, 10): out["%s %d" % (k, i)] = a
        else:
            for d in ("Left", "Right", "Up", "Down"): out["%s %s" % (k, d)] = a
    return out

def block(prof):
    """The lines gen writes between the markers."""
    k = current(prof)
    lock, rest = [], []
    if k["edit"]:
        lock.append('bind "%s" { %s; }' % (k["edit"], RUN % ("edit", "EDIT")))
        rest.append('bind "%s" { SwitchToMode "Locked"; %s; }' % (k["edit"], RUN % ("edit", "EDIT")))
    if k["new_tab"]:
        lock.append('bind "%s" { %s; }' % (k["new_tab"], RUN % ("new --here", "NEW")))
    if k["note"]:
        lock.append('bind "%s" { %s; }' % (k["note"], RUN % ("note --here", "NOTE")))
    if k["controls"]:
        lock.append('bind "%s" { SwitchToMode "Normal"; }' % k["controls"])
        rest.append('bind "%s" { SwitchToMode "Locked"; }' % k["controls"])
    if k["tabs"]:
        lock += ['bind "%s %d" { GoToTab %d; }' % (k["tabs"], i, i) for i in range(1, 10)]
    if k["panes"]:
        lock += ['bind "%s Left"  { MoveFocusOrTab "Left"; }' % k["panes"],
                 'bind "%s Right" { MoveFocusOrTab "Right"; }' % k["panes"],
                 'bind "%s Up"    { MoveFocus "Up"; }' % k["panes"],
                 'bind "%s Down"  { MoveFocus "Down"; }' % k["panes"]]
    if k["zoom"]:
        lock.append('bind "%s" { ToggleFocusFullscreen; }' % k["zoom"])
    if k["leave"]:
        lock.append('bind "%s" { Detach; }' % k["leave"])
    out = [BEGIN, NOTE, "    locked {"] + ["        " + l for l in lock] + ["    }"]
    if rest:
        out += ['    shared_except "locked" {'] + ["        " + l for l in rest] + ["    }"]
    return "\n".join(out + [END])

def put(text, prof):
    """(the config with the block rewritten, what happened): "updated",
    "same", or "no markers" (then the text comes back untouched)."""
    lines = text.split("\n")
    try:
        i = next(n for n, l in enumerate(lines) if l.strip().startswith("// ── PHOSPHOR KEYS"))
        j = next(n for n, l in enumerate(lines) if n > i and l.strip().startswith("// ── END PHOSPHOR KEYS"))
    except StopIteration:
        return text, "no markers"
    new = "\n".join(lines[:i] + block(prof).split("\n") + lines[j + 1:])
    return new, ("same" if new == text else "updated")

def conflicts(keys, action, key):
    """(deck actions, tools) that already use what this key would take."""
    if not key: return [], []
    mine = expand({action: key})
    others = expand({a: k for a, k in keys.items() if a != action})
    others["Ctrl q"] = "leave (Ctrl-q)"
    deck = sorted({others[k] for k in mine if k in others})
    tools = sorted({t for t, ks in TAKEN.items() for k in mine if k in ks})
    return deck, tools

def guide_rows(rows, prof):
    """keys.json's deck section with the keys this profile really uses."""
    k = current(prof)
    swap = {"Alt-r": dash(k["edit"]), "Alt-n": dash(k["new_tab"]), "Alt-j": dash(k["note"]), "Alt-z": dash(k["zoom"]),
            "Alt-g": dash(k["controls"]),
            "Alt-1 … Alt-9": (dash(k["tabs"] + " 1") + " … " + dash(k["tabs"] + " 9")) if k["tabs"] else "off",
            "Alt-← ↑ ↓ →": (dash(k["panes"]) + "-← ↑ ↓ →") if k["panes"] else "off",
            "Alt-x · Ctrl-q": (dash(k["leave"]) + " · Ctrl-q") if k["leave"] else "Ctrl-q"}
    return [[swap.get(a, a), b] for a, b in rows]

def phone_macro(key):
    """"Alt r" → "ALT r", as Termux's extra keys write it."""
    return " ".join(w.upper() if w in ("Alt", "Ctrl", "Shift") else w for w in key.split())

# ── [keys] in the profile ─────────────────────────────────────
def set_text(text, action, key):
    """action = "key" under [keys]; the section is added at the end if missing."""
    line = '%-8s = "%s"' % (action, key)
    m = re.search(r"^\[keys\]\s*$", text, re.M)
    if not m:
        return text.rstrip("\n") + "\n\n[keys]\n" + line + "\n"
    start = m.end()
    nxt = re.search(r"^\s*\[", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    body = text[start:end]
    pat = re.compile(r'^%s\s*=.*$' % re.escape(action), re.M)
    body = pat.sub(line, body, count=1) if pat.search(body) else body.rstrip("\n") + "\n" + line + "\n"
    if nxt and not body.endswith("\n\n"): body = body.rstrip("\n") + "\n\n"
    return text[:start] + body + text[end:]

# ── the screen ────────────────────────────────────────────────
def capture():
    """One key combination, as zellij writes it; None for Esc; "" for Backspace (off)."""
    import termios, tty, select
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            data = os.read(fd, 64)
            while select.select([fd], [], [], 0.03)[0]:
                data += os.read(fd, 64)
            data = re.sub(rb"\x1b\[<\d+;\d+;\d+[Mm]", b"", data)   # the tap that got here, released
            if data: break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return parse(data)

ARROWS = {"A": "Up", "B": "Down", "C": "Right", "D": "Left"}
MODS = {"2": "Shift", "3": "Alt", "4": "Shift Alt", "5": "Ctrl", "6": "Ctrl Shift", "7": "Ctrl Alt", "8": "Ctrl Shift Alt"}

def parse(data):
    s = data.decode("utf-8", "ignore")
    if s == "\x1b": return None
    if s in ("\x7f", "\x08"): return ""
    m = re.match(r"\x1b\[1;(\d)([ABCD])$", s)
    if m: return "%s %s" % (MODS.get(m.group(1), ""), ARROWS[m.group(2)])
    if len(s) == 2 and s[0] == "\x1b":
        c = s[1]
        if 1 <= ord(c) <= 26: return "Ctrl Alt " + chr(ord(c) + 96)
        if c.isprintable(): return "Alt " + c
    if len(s) == 1 and 1 <= ord(s) <= 26 and s not in ("\t", "\r", "\n"):
        return "Ctrl " + chr(ord(s) + 96)
    return "?"

def save(action, key):
    p = deckconf.path()
    if deckconf.example():
        return "there's no profile yet: phosphor init"
    text = open(p).read()
    new = set_text(text, action, key)
    try:
        prof = deckconf.tomllib.loads(new)
    except Exception as e:
        return "the profile wouldn't parse: %s" % str(e)[:50]
    if current(prof).get(action) != key:
        return "the profile didn't take it"
    open(p + ".bak", "w").write(text)
    open(p, "w").write(new)
    import subprocess
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None

def main():
    argv = sys.argv[1:]
    prof, _ = deckconf.load()
    if "--kdl" in argv:
        print(block(prof)); return 0
    if not sys.stdin.isatty():
        for a, what, _, _ in ACTIONS:
            print("%-9s %-12s %s" % (a, dash(current(prof)[a]), what))
        return 0
    import edit
    msg = ""
    while True:
        prof, _ = deckconf.load()
        keys = current(prof)
        items = [(dash(keys[a]), what, a, kind) for a, what, _, kind in ACTIONS]
        title = "shortcuts" + ("  ·  " + msg if msg else "")
        it = edit.pick(title, items)
        msg = ""
        if not it: return 0
        _, what, action, kind = it
        if kind == "prefix":
            got = edit.pick("%s: which modifier? (then %s)" % (what.split(":")[0], "1..9" if action == "tabs" else "arrows"),
                            [(p or "off", "") for p in PREFIXES])
            if not got: continue
            key = "" if got[0] == "off" else got[0]
        else:
            sys.stdout.write("\x1b[H\x1b[2J\n  " + BLOOM + what + RST + "\n\n  " + FG +
                             "press the new key (Alt or Ctrl with something)" + RST + "\n  " + DIM +
                             "Backspace turns it off · Esc leaves it as it is" + RST + "\n")
            sys.stdout.flush()
            key = capture()
            if key is None: continue
            if key == "?":
                msg = AMB + "that key can't be a shortcut: use Alt or Ctrl with it" + RST; continue
        deck, tools = conflicts(keys, action, key)
        if deck or tools:
            who = ", ".join(deck + tools)
            ok = edit.pick("%s is also used by %s: take it anyway?" % (dash(key), who),
                           [("yes", "take it"), ("no", "keep %s" % dash(keys[action]))])
            if not ok or ok[0] != "yes": continue
        err = save(action, key)
        msg = (RED + "not saved: " + err + RST) if err else (PH + "%s is now %s" % (action, dash(key)) + RST)

if __name__ == "__main__":
    sys.exit(main() or 0)
