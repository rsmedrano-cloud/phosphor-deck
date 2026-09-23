"""phosphor setup - add or remove machines and pick the color, without
editing files by hand. Project Phosphor Deck.

It edits deck.toml as text, so your comments and custom tabs survive: a
machine is one [[hosts]] block, the color is one line. Every change is
parsed back before it touches the real file, and the first one of a run
leaves deck.toml.bak behind.
"""
import os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, mesh
from init import ask, pick, yes, discover, try_ssh, probe, host_block

PHOSPHOR = os.path.join(REPO, "phosphor")
UDIR  = os.path.expanduser("~/.config/systemd/user")

THEMES = [("p31",   "green phosphor · VT100, oscilloscopes"),
          ("p3",    "amber · IBM 5151, Wyse terminals"),
          ("p4",    "white · black & white terminals"),
          ("paper", "paper · e-ink screens")]

# Roles you can give a new machine. There is only one brain: this one.
ROLES = [("work",    "projects live here"),
         ("desktop", "a desk machine"),
         ("storage", "disks only"),
         ("node",    "small always-on box: a Pi, a NAS"),
         ("viewer",  "only looks at the deck: never polled or mounted")]

# ── text surgery on deck.toml ─────────────────────────────────
def host_spans(lines):
    """[(start, end, name)] for each [[hosts]] block. A block runs until the
    first blank line or the next table header."""
    out = []
    for i, l in enumerate(lines):
        if l.strip() != "[[hosts]]":
            continue
        j, name = i + 1, None
        while j < len(lines) and lines[j].strip() and not lines[j].lstrip().startswith("["):
            m = re.match(r'\s*name\s*=\s*"([^"]*)"', lines[j])
            if m: name = m.group(1)
            j += 1
        out.append((i, j, name))
    return out

def add_host_text(text, h):
    lines = text.split("\n")
    spans = host_spans(lines)
    if spans:
        at = spans[-1][1]
        lines[at:at] = [""] + host_block(h)
    else:
        at = next((i for i, l in enumerate(lines) if l.strip() == "[[tabs]]"), len(lines))
        lines[at:at] = host_block(h) + [""]
    return "\n".join(lines)

def remove_host_text(text, name):
    lines = text.split("\n")
    for s, e, n in host_spans(lines):
        if n == name:
            if s > 0 and not lines[s - 1].strip():
                s -= 1            # take the gap before it, so no double gap is left
            del lines[s:e]
            break
    return "\n".join(lines)

def set_deck_text(text, key, value):
    """key = "value" in [deck]: replaced where it is, else added under [deck]."""
    pat = re.compile(r'^(\s*%s\s*=\s*)"[^"]*"' % re.escape(key), re.M)
    if pat.search(text):
        return pat.sub(lambda m: m.group(1) + '"%s"' % value, text, count=1)
    return re.sub(r"^\[deck\]\s*$", '[deck]\n%-7s = "%s"' % (key, value), text, count=1, flags=re.M)

def set_theme_text(text, theme):
    return set_deck_text(text, "theme", theme)

def set_notes_text(text, folder):
    """folder = "..." in [notes]: replaced where it is, the table added if
    it's missing (deck.toml doesn't come with one)."""
    pat = re.compile(r'^(\s*folder\s*=\s*)"[^"]*"', re.M)
    if "[notes]" in text and pat.search(text):
        return pat.sub(lambda m: m.group(1) + '"%s"' % folder, text, count=1)
    if "[notes]" in text:
        return re.sub(r"^\[notes\]\s*$", '[notes]\nfolder = "%s"' % folder, text, count=1, flags=re.M)
    return text.rstrip("\n") + "\n\n[notes]\nfolder = \"%s\"\n" % folder

def remove_notes_text(text):
    """Drop the [notes] table: back to the private default."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip() == "[notes]":
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("["):
                i += 1
            if i < len(lines) and not lines[i].strip():
                i += 1               # the blank line after the table too
            continue
        out.append(lines[i]); i += 1
    return "\n".join(out)

_backed = [False]
def save(text, check):
    """Parse first; write only a profile that reads back right."""
    try:
        prof = deckconf.tomllib.loads(text)
    except Exception as e:
        print(row(BAD, "not saved", str(e)[:50])); return False
    if not check(prof):
        print(row(BAD, "not saved", "the result doesn't look right")); return False
    p = deckconf.path()
    if not _backed[0]:
        shutil.copy(p, p + ".bak"); _backed[0] = True
    open(p, "w").write(text)
    print(row(OK, "saved", p, note="backup: deck.toml.bak"))
    return True

# ── screens ───────────────────────────────────────────────────
def swatch(name):
    P = PALETTES[name]
    c = lambda k: rgb(*P[k])
    return (c("ph") + "██" + c("bloom") + "▓▓" + c("mute") + "▒▒" + c("dim") + "░░ "
            + c("fg") + "PHOSPHOR " + c("warn") + "⚠ " + c("bad") + "✗" + RST)

def show(prof):
    print("\n" + rule("machines"))
    for h in deckconf.hosts(prof):
        if h.get("local"):
            where, sym = "this machine", OK
        else:
            where, sym = deckconf.target(h), DIM + "·" + RST
        what = h.get("mount") or ", ".join(h.get("mounts", [])) or "not mounted"
        print(row(sym, h["name"], h.get("role", "?"), note=where + " · " + what))
    kind, control = mesh.current(prof)
    print(row(OK, "network", kind, note=control or ""))
    t = theme_name(prof)
    print(row(OK, "color", t, note=swatch(t)))
    print(row(OK, "editor", deckconf.editor(prof, ask_login=False)))
    print(row(OK, "shell", deckconf.shell(prof)))
    folder = (prof.get("notes") or {}).get("folder")
    print(row(OK, "notebook", folder.replace(os.path.expanduser("~"), "~", 1) if folder else "private"))

def add(prof, text):
    have = {h["name"] for h in prof.get("hosts", [])}
    print("\n" + rule("add a machine"))
    print("    " + DIM + "looking around (tailscale, ~/.ssh/config)..." + RST)
    cands, me = discover(mesh.current(prof)[0] != "none")
    names = [n for n, c in sorted(cands.items())
             if n not in have and n != me and not c.get("viewer_only")]
    opts = ["%-22s %s" % (n, "offline" if cands[n]["offline"] else (cands[n].get("ip") or "ssh config"))
            for n in names]
    opts += ["another one: type its name or ssh alias", "back"]
    k = pick("which machine?", opts, 0)
    if k == len(opts) - 1:
        return text, None
    if k == len(opts) - 2:
        n = ask("name or ssh alias", "")
        if not n: return text, None
        c = {"ip": None}
    else:
        n = names[k]; c = cands[n]

    target = n
    ok, out = try_ssh(n)
    if not ok and ("denied" in out.lower() or "publickey" in out.lower()):
        print(row(WARN, n, "doesn't take this machine's key yet"))
        if yes("copy the key now with ssh-copy-id? (asks its password once)", True):
            u = ask("user on %s" % n, os.environ.get("USER", ""))
            target = "%s@%s" % (u, n) if u else n
            subprocess.run(["ssh-copy-id", target])
    print("    " + DIM + "probing %s..." % n + RST)
    info = probe(target)
    if info is None:
        print(row(BAD, n, "no ssh answer", note="nothing changed")); return text, None

    r = pick("what is %s?" % n, ["%-8s %s" % rl for rl in ROLES], 3)
    h = {"name": n, "role": ROLES[r][0], "ssh": n}
    if "@" in info.get("target", ""):
        h["user"] = info["target"].split("@")[0]
    if info.get("user") and info["user"] != os.environ.get("USER"):
        h["user"] = info["user"]
    if c.get("ip"): h["ip"] = c["ip"]
    if h["role"] != "viewer":
        disks = info.get("mounts", [])
        mopts = ["%-24s %s" % (t, s) for t, s in disks] + ["don't mount it"]
        m = pick("which disk goes into ~/fleet/%s ?" % n, mopts, 0)
        if m < len(disks):
            h["mount"] = disks[m][0]

    t2 = add_host_text(text, h)
    if not save(t2, lambda p: any(x.get("name") == n for x in p.get("hosts", []))):
        return text, None
    return t2, n

def remove(prof, text):
    rem = [h for h in deckconf.hosts(prof) if not h.get("local")]
    print("\n" + rule("remove a machine"))
    if not rem:
        print("    " + DIM + "only this machine is in the deck" + RST); return text, None
    opts = ["%-22s %s" % (h["name"], h.get("role", "")) for h in rem] + ["back"]
    k = pick("which one?", opts, len(opts) - 1)
    if k == len(opts) - 1:
        return text, None
    h = rem[k]
    if h.get("role") == "work":
        print(row(WARN, "heads up", "tabs that ssh to @work will lose their target"))
    if not yes("remove %s from the deck?" % h["name"], False):
        return text, None
    t2 = remove_host_text(text, h["name"])
    if save(t2, lambda p: all(x.get("name") != h["name"] for x in p.get("hosts", []))):
        return t2, h["name"]
    return text, None

def color(prof, text):
    print("\n" + rule("color"))
    cur = theme_name(prof)
    keys = [k for k, _ in THEMES]
    opts = ["%-6s %s  %s" % (k, swatch(k), DIM + d + RST) for k, d in THEMES]
    i = pick("pick a phosphor", opts, keys.index(cur) if cur in keys else 0)
    if keys[i] == cur:
        return text, False
    t2 = set_theme_text(text, keys[i])
    if save(t2, lambda p: (p.get("deck") or {}).get("theme") == keys[i]):
        return t2, True
    return text, False

def tools(prof, text):
    import init
    print("\n" + rule("editor and shell"))
    changed = False
    ed, sh = init.tools()
    for key, val in (("editor", ed), ("shell", sh)):
        if val and (prof.get("deck") or {}).get(key) != val:
            t2 = set_deck_text(text, key, val)
            if save(t2, lambda p, k=key, v=val: (p.get("deck") or {}).get(k) == v):
                text, changed = t2, True
    return text, changed

def notes_folder(prof, text):
    import notes
    print("\n" + rule("notebook"))
    cur = (prof.get("notes") or {}).get("folder")
    print(row(OK, "now", cur.replace(os.path.expanduser("~"), "~", 1) if cur else "private"))
    old_path = notes.PATH
    folder = notes.choose_folder(cur)
    if (folder or None) == (cur or None):
        return text, False
    if folder:
        t2 = set_notes_text(text, folder)
        ok = save(t2, lambda p: (p.get("notes") or {}).get("folder") == folder)
    else:
        t2 = remove_notes_text(text)
        ok = save(t2, lambda p: not (p.get("notes") or {}).get("folder"))
    if not ok:
        return text, False
    new_path = os.path.join(folder, "notes.md") if folder else os.path.join(notes.notes_dir(), "notes.md")
    moved = notes.migrate(old_path, new_path)
    print(row(OK, "moved" if moved else "nothing to move", ", ".join(moved) or old_path))
    return t2, True

def apply(added, removed):
    print("\n" + rule("apply"))
    for n in removed:
        u = "fleet-%s.service" % n
        subprocess.run(["systemctl", "--user", "disable", "--now", u], capture_output=True)
        p = os.path.join(UDIR, u)
        if os.path.exists(p):
            os.remove(p); print(row(OK, u, "unmounted and removed"))
    subprocess.run([sys.executable, PHOSPHOR, "gen"])
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    for n in added:
        u = "fleet-%s.service" % n
        if os.path.exists(os.path.join(UDIR, u)):
            r = subprocess.run(["systemctl", "--user", "enable", "--now", u], capture_output=True)
            print(row(OK if r.returncode == 0 else BAD, u,
                      "mounted" if r.returncode == 0 else "failed: journalctl --user -u " + u))
    inside = bool(os.environ.get("ZELLIJ"))
    if inside:
        print(row(WARN, "restart", "you're inside the deck",
                  note="it closes, and you're back in by yourself in seconds"))
    if not yes("restart the deck now so everything shows the changes?", True):
        print("    " + DIM + "later: phosphor restart" + RST); return
    # Detached: restarting kills the pane this runs in.
    os.makedirs(os.path.expanduser("~/.cache/phosphor"), exist_ok=True)
    log = open(os.path.expanduser("~/.cache/phosphor/restart.log"), "w")
    subprocess.Popen([sys.executable, PHOSPHOR, "restart"], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    print(row(OK, "restart", "on its way", note="log: ~/.cache/phosphor/restart.log"))
    time.sleep(2 if inside else 0)

def run():
    if deckconf.tomllib is None:
        print("  " + deckconf.ERR); return 1
    p = deckconf.path()
    if not os.path.exists(deckconf.CONF) and "PHOSPHOR_PROFILE" not in os.environ:
        print("  no profile yet: run " + PH + "phosphor init" + RST + " first"); return 1
    prof, _ = deckconf.load()
    if prof is None:
        print("  can't read %s: %s" % (p, deckconf.ERR)); return 1
    lh = next((h for h in prof.get("hosts", []) if h.get("local")), None)
    if not lh or lh.get("role") != "brain":
        print("  setup runs on the brain, where the deck lives"); return 1

    text = open(p).read()
    added, removed, dirty = [], [], False
    while True:
        prof = deckconf.tomllib.loads(text)
        print()
        print(BLOOM + "  PHOSPHOR DECK · setup" + RST + DIM + "   " + p + RST)
        show(prof)
        print()
        webon = (prof.get("deck") or {}).get("web", False)
        opts = ["add a machine", "remove a machine", "change the color",
                "connect a phone or tablet",
                "apply: regenerate and restart" + ("  (changes waiting)" if dirty else ""),
                "quit",
                "browser access: turn it " + ("off" if webon else "on (only inside your tailnet)"),
                "tunnels: keep your ssh config's LocalForward tunnels up",
                "editor and shell",
                "notebook: where it lives (private, or a vault you sync)"]
        k = pick("what now?", opts, 4 if dirty else 0)
        if k == 0:
            text, n = add(prof, text)
            if n: added.append(n); dirty = True
        elif k == 1:
            text, n = remove(prof, text)
            if n:
                removed.append(n); dirty = True
                if n in added: added.remove(n)
        elif k == 2:
            text, ch = color(prof, text)
            dirty = dirty or ch
        elif k == 3:
            import phone
            phone.instructions(prof)
            ask("Enter to go back", "")
        elif k == 4:
            apply(added, removed); return 0
        elif k == 8:
            text, ch = tools(prof, text)
            dirty = dirty or ch
        elif k == 9:
            text, ch = notes_folder(prof, text)
            dirty = dirty or ch
        elif k == 7:
            import tunnels
            tunnels.interactive()
            text = open(p).read()
        elif k == 6:
            import web as webmod
            (webmod.off() if webon else webmod.on())
            text = open(p).read()
        else:
            if dirty and yes("apply the changes before leaving?", True):
                apply(added, removed)
            return 0

if __name__ == "__main__":
    sys.exit(run() or 0)
