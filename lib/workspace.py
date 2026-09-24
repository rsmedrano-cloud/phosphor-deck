"""phosphor workspace — a tab per idea: its own folder and its own assistants.

    phosphor workspace new [NAME]      folder + git + a tab, asks what's missing
        --shape one|two|shell          one assistant, two side by side, or one + a shell
        --parts "frontend backend"     the two folders (two only)
        --assistant claude             which assistant CLI
        --brief FILE                   what it's about, copied as BRIEF.md
        --note TEXT                    the brief from the notebook note whose title has TEXT
        --note-file FILE               the brief from one note's exact text (the NOTES tab uses it)
        --folder-only                  write the folder, don't touch the profile or tabs
    phosphor workspace open NAME       its tab (from inside the deck)
    phosphor workspace list            the workspaces under your projects folder

A workspace lives in [deck] projects (default ~/projects)/NAME. Every assistant
folder gets an AGENTS.md saying what it owns; the workspace keeps its own
NOTES.md, where the assistants hand work to each other. Existing files are
never overwritten: pointing it at a folder you have adds only what's missing.
"""
import json, os, re, shlex, shutil, subprocess, sys, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

HOME = os.path.expanduser("~")
PHOSPHOR = os.path.join(REPO, "phosphor")
SHAPES = [("one", "one assistant"), ("two", "two assistants side by side (frontend | backend)"),
          ("shell", "an assistant and a shell")]
# What each assistant reads by itself, besides AGENTS.md, and how it picks up
# where it left after a restart.
CONTEXT = {"claude": "CLAUDE.md", "gemini": "GEMINI.md"}
RESUME = {"claude": "claude --continue || exec claude",
          "aider": "aider --restore-chat-history || exec aider"}
# (binary, flags before a first message): assistants that start from a message
# and stay open. notes.py's c uses the same list. aider can't really do this
# (its --message "disables chat mode": answers once, exits) -- assistant_first_cmd()
# fakes it for aider specifically, so it's still in this list.
FIRST = {"claude": [], "gemini": ["-i"], "codex": [], "opencode": ["--prompt"], "aider": ["--message"]}

def root(prof=None):
    if prof is None:
        prof, _ = deckconf.load()
    return os.path.expanduser(((prof or {}).get("deck") or {}).get("projects", "~/projects"))

def slug(text, words=5):
    """A folder name from a title: 'Índice de conversaciones IA' -> indice-de-conversaciones-ia."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    parts = re.findall(r"[a-z0-9]+", t)[:words]
    return "-".join(parts)[:40].strip("-")

def tilde(p):
    return p.replace(HOME, "~", 1) if p == HOME or p.startswith(HOME + "/") else p

def assistant_first_cmd(a, msg_expr):
    """The shell command that starts assistant `a` with `msg_expr` -- already
    a shell expression for the message (a quoted literal, or notes.py's
    chat()'s `"$(cat FILE)"`, read at run time instead of embedded) -- as
    its first message, staying interactive after. The one exception is
    aider: --message answers once and exits (its own "disables chat mode"),
    so there's no flag that both gives it a first message and stays
    interactive -- this answers once non-interactively instead, then hands
    off to a normal interactive aider that reloads that exchange from its
    own chat-history file."""
    if a == "aider":
        return "aider %s %s --yes-always; exec aider --restore-chat-history" % (
            " ".join(FIRST["aider"]), msg_expr)
    return "exec %s %s" % (" ".join([a] + FIRST.get(a, [])), msg_expr)

def assistant_line(a, first=None):
    """The shell line a pane runs: resume if it can, a first message if given."""
    if first:
        return assistant_first_cmd(a, shlex.quote(first))
    return RESUME.get(a, "exec " + a)

def folders(name, shape, parts):
    """(folder relative to the workspace, role) for each assistant."""
    if shape == "two":
        return [(p, p) for p in parts]
    return [("", None)]

def tab_spec(name, base, shape, parts, a, first=None):
    """The [[tabs]] entry: panes with their working folders."""
    here = tilde(base)
    def ai(sub, msg=None):
        return {"cmd": "bash", "args": ["-lc", assistant_line(a, msg)],
                "cwd": here + ("/" + sub if sub else "")}
    if shape == "two":
        return {"name": name.upper(), "split": "cols",
                "panes": [ai(p, first) for p in parts]}
    panes = [ai("", first)]
    if shape == "shell":
        panes = [dict(panes[0], size="65%"), {"cwd": here}]
        return {"name": name.upper(), "split": "cols", "panes": panes}
    return {"name": name.upper(), "panes": panes}

def agents_md(name, base, shape, parts, role=None, has_brief=False):
    book = tilde(os.path.join(base, "NOTES.md"))
    out = ["# %s" % name, ""]
    if role:
        others = [p for p in parts if p != role]
        out += ["You are the **%s** assistant of the %s workspace. Your folder is `%s`;"
                % (role, name, tilde(os.path.join(base, role))),
                "stay in it. %s by another assistant, in its own folder%s." % (
                    ", ".join("`%s`" % o for o in others) + (" is handled" if len(others) == 1 else " are handled"),
                    "" if len(others) != 1 else " (`%s`)" % tilde(os.path.join(base, others[0]))), ""]
    else:
        out += ["You are the assistant of the %s workspace, in `%s`." % (name, tilde(base)), ""]
    out += ["## Start here", ""]
    if has_brief:
        out.append("- Read `%s`: the idea this workspace was opened for." % tilde(os.path.join(base, "BRIEF.md")))
    out += ["- Read the workspace notebook: `phosphor notes --file %s` (newest first)." % book,
            "", "## Handing off", "",
            "The notebook is how the people and assistants here talk to each other.",
            "Write what someone else needs to know: a decision, an interface, what's pending.", "",
            "    phosphor note --file %s --by %s --kind decision \"title\"" % (book, role or "assistant"),
            "    # kinds: note idea decision todo summary; - reads a longer body from stdin", "",
            "Leave a short summary note before you stop.", ""]
    return "\n".join(out)

def plan(name, base, shape="one", parts=(), a="claude", brief=None):
    """{relative path: content} for the files a workspace needs."""
    parts = list(parts) if shape == "two" else []
    files = {}
    if brief is not None:
        files["BRIEF.md"] = brief.rstrip("\n") + "\n"
    files["NOTES.md"] = ("# %s notes\n\nShared notebook: you and your assistants write here.\n\n" % name)
    for sub, role in folders(name, shape, parts):
        at = (sub + "/") if sub else ""
        files[at + "AGENTS.md"] = agents_md(name, base, shape, parts, role, brief is not None)
        if a in CONTEXT:
            files[at + CONTEXT[a]] = "@AGENTS.md\n"
    if shape == "two":
        # the whole workspace, for anyone opening it at the top
        files["AGENTS.md"] = agents_md(name, base, "one", [], None, brief is not None) + \
            "\n## Parts\n\n" + "".join("- `%s/`: its own assistant, see its AGENTS.md\n" % p for p in parts)
    return files

def write_files(base, files):
    """Write what's missing; never overwrite. Returns (written, kept)."""
    written, kept = [], []
    for rel, content in files.items():
        p = os.path.join(base, rel)
        if os.path.exists(p):
            kept.append(rel); continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        written.append(rel)
    if not os.path.isdir(os.path.join(base, ".git")) and shutil.which("git"):
        subprocess.run(["git", "init", "-q", base], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # A first commit for the scaffold itself (AGENTS.md, NOTES.md...):
        # without one, dirty_workspaces() (#36) would flag every workspace
        # as dirty from the moment it's created, before anyone's actually
        # changed anything. -c user.*, not the global config: this must
        # work even where nobody's ever set a git identity.
        subprocess.run(["git", "-C", base, "add", "-A"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", base, "-c", "user.name=phosphor", "-c", "user.email=phosphor@localhost",
                        "commit", "-q", "-m", "workspace scaffold"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return written, kept

def installed():
    import newtab
    return [b for b, _ in newtab.ASSISTANTS if b in FIRST and newtab.have(b)]

def from_note(text):
    """(title, raw) of the one note whose title contains text, else an error string."""
    import notes
    found = [e for e in notes.entries() if text.lower() in e["title"].lower()]
    if len(found) != 1:
        return None, ("no note's title has %r" % text if not found else
                      "%d notes match %r: be more specific" % (len(found), text))
    return found[0], None

def zj(*a):
    import newtab
    return newtab.zj(*a)

def open_tab(name, spec=None):
    """Go to its tab, or open it. spec: a one-off layout (the first launch)."""
    import newtab, gen
    if not os.environ.get("ZELLIJ"):
        print("  " + DIM + "open it from inside the deck: phosphor workspace open %s" % name.lower() + RST)
        return
    tab = name.upper()
    if tab in newtab.taken_names():
        zj("go-to-tab-name", tab); return
    if spec:
        prof, _ = deckconf.load()
        d = os.path.expanduser("~/.cache/phosphor/workspace")
        os.makedirs(d, exist_ok=True)
        lay = os.path.join(d, "%s-%s.kdl" % (name.lower(), time.strftime("%Y%m%d-%H%M%S")))
        with open(lay, "w") as f:
            f.write(gen.tab_kdl(spec, gen.Ctx(prof or {}), "phosphor workspace"))
    else:
        lay = os.path.expanduser("~/.config/zellij/layouts/tab-%s.kdl" % tab.lower())
        if not os.path.exists(lay):
            print("  " + WARN + " no layout for %s: phosphor gen" % tab); return
    zj("new-tab", "--layout", lay, "--name", tab)

def keep(spec):
    """Into the profile, then gen. False if either fails (and says why)."""
    import keep as k
    blk = k.block(spec["name"], spec["panes"], spec.get("split"))
    if not k.save(spec["name"], blk):
        return False
    r = subprocess.run([sys.executable, PHOSPHOR, "gen"], capture_output=True, text=True)
    if r.returncode != 0:
        print("  " + BAD + " phosphor gen failed:")
        print("\n".join("    " + l for l in (r.stdout + r.stderr).strip().splitlines()[-8:]))
        return False
    return True

def taken_tab(prof, tab, base):
    """A profile tab with this name that isn't this workspace."""
    for t in (prof or {}).get("tabs", []):
        if t.get("name") == tab:
            cwds = [p.get("cwd", "") for p in t.get("panes", [])]
            return not any(os.path.expanduser(c) == base or os.path.expanduser(c).startswith(base + "/")
                           for c in cwds if c)
    return False

def new(argv):
    from init import ask, pick, yes
    def take(flag):
        if flag in argv:
            i = argv.index(flag)
            v = argv[i + 1] if i + 1 < len(argv) else ""
            del argv[i:i + 2]
            return v
    shape, parts, a = take("--shape"), take("--parts"), take("--assistant")
    brief_file, note_text, note_file = take("--brief"), take("--note"), take("--note-file")
    folder_only = "--folder-only" in argv
    argv = [x for x in argv if not x.startswith("--")]
    tty = sys.stdin.isatty()
    prof, _ = deckconf.load()

    brief, title, note = None, "", None
    if note_text:
        note, err = from_note(note_text)
        if err: print("  " + BAD + " " + err); return 1
        brief, title = note["raw"], note["title"]
    elif note_file:                                   # the NOTES tab hands over one exact note
        import notes
        try: note = notes.parse(open(note_file).read().strip("\n"))
        except (OSError, AttributeError): print("  " + BAD + " not a note: " + note_file); return 1
        brief, title = note["raw"], note["title"]
    elif brief_file:
        try: brief = open(os.path.expanduser(brief_file)).read()
        except OSError as e: print("  " + BAD + " " + str(e)); return 1
        title = next((l.lstrip("#").strip() for l in brief.splitlines() if l.strip()), "")
        m = re.match(r"\S+ \S+ · \w+ · [^·]+? · (.*)", title)       # a note's own header
        title = m.group(1) if m else title

    print(rule("new workspace"))
    name = slug(argv[0]) if argv else ""
    if not name:
        if tty: name = slug(ask("its name", slug(title)))
        elif title: name = slug(title)
        else: print("  a name is needed: phosphor workspace new NAME"); return 1
    if not name:
        print("  " + BAD + " no name"); return 1
    base = os.path.join(root(prof), name)

    if shape not in dict(SHAPES):
        if not tty: shape = "one"
        else: shape = SHAPES[pick("what goes in its tab?", [l for _, l in SHAPES], 0)][0]
    parts = (parts or "").split()
    if shape == "two" and len(parts) != 2:
        parts = ask("its two parts", "frontend backend").split()[:2] if tty else ["frontend", "backend"]
        if len(parts) != 2: print("  " + BAD + " two parts, like: frontend backend"); return 1
    parts = [slug(p) for p in parts]

    have = installed()
    if not a:
        if not have:
            print("  " + BAD + " no assistant installed: " + ", ".join(FIRST)); return 1
        a = have[0] if len(have) == 1 or not tty else have[pick("which assistant?", have, 0)]
    if a not in FIRST:
        print("  " + BAD + " unknown assistant %r: %s" % (a, ", ".join(FIRST))); return 1

    tab = name.upper()
    if not folder_only and not os.path.exists(os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)):
        print("  " + BAD + " no profile to keep the tab in: phosphor init, or --folder-only"); return 1
    if not folder_only and taken_tab(prof, tab, base):
        print("  " + BAD + " your profile already has a %s tab that isn't this workspace: pick another name" % tab)
        return 1
    if os.path.isdir(base) and os.listdir(base):
        print(row(WARN, "the folder exists", tilde(base), note="only what's missing is added"))
        if tty and not yes("use it?", True): return 1

    files = plan(name, base, shape, parts, a, brief)
    written, kept = write_files(base, files)
    print(row(OK, "folder", tilde(base)))
    for rel in written: print("      " + DIM + "+ " + rel + RST)
    for rel in kept:    print("      " + DIM + "= " + rel + " (yours, left alone)" + RST)
    if folder_only:
        return 0

    spec = tab_spec(name, base, shape, parts, a)
    if not keep(spec):
        return 1
    print(row(OK, "tab", tab, note="kept in your profile"))
    first = None
    if brief is not None or written:
        first = ("Read AGENTS.md%s and the workspace notebook, then tell me in a few lines "
                 "what this is about and what you'd do first." % (", BRIEF.md" if brief is not None else ""))
    open_tab(name, tab_spec(name, base, shape, parts, a, first) if first else None)
    if note is not None:
        mark_note(note, name, base)
    return 0

def mark_note(note, name, base):
    """The note says where it went."""
    import notes
    line = "→ workspace %s (%s)" % (name, tilde(base))
    if line in note["raw"]: return
    body = note["body"] + ([""] if note["body"] else []) + [line]
    notes.replace(notes.PATH, note["raw"], notes.rekind(note["raw"], body=body))

def names():
    """Every workspace under root() (it has a NOTES.md), sorted."""
    try:
        return sorted(n for n in os.listdir(root()) if os.path.isfile(os.path.join(root(), n, "NOTES.md")))
    except FileNotFoundError:
        return []

def listing():
    r = root()
    ns = names()
    if not ns:
        print("  no workspaces in %s yet: phosphor workspace new" % tilde(r)); return 0
    for n in ns:
        print("  %-24s %s" % (n, tilde(os.path.join(r, n))))
    return 0

def git_status(base):
    """(dirty, ahead, behind) for a workspace's own git repo (write_files()
    always `git init`s one), or None if it somehow isn't one. ahead/behind
    are 0 without an upstream -- phosphor never adds one itself, so most
    workspaces won't have one until you set one up by hand."""
    if not os.path.isdir(os.path.join(base, ".git")):
        return None
    def sh(*a):
        try:
            return subprocess.run(["git", "-C", base] + list(a),
                                  capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
    dirty = bool(sh("status", "--porcelain").strip())
    ahead = behind = 0
    if sh("rev-parse", "--abbrev-ref", "@{u}").strip():
        counts = sh("rev-list", "--left-right", "--count", "HEAD...@{u}").split()
        if len(counts) == 2:
            ahead, behind = int(counts[0]), int(counts[1])
    return dirty, ahead, behind

def dirty_workspaces():
    """[(name, dirty, ahead, behind)] for every workspace with something
    worth a look: uncommitted changes, or commits ahead/behind an upstream
    -- "one device, then another" makes it easy to leave one dirty and
    forget which machine has the changes (#36). Empty when every workspace
    is clean and, if it has an upstream at all, pushed."""
    out = []
    r = root()
    for name in names():
        st = git_status(os.path.join(r, name))
        if st and any(st):
            out.append((name,) + st)
    return out

NOTES_SEEN = os.path.join(deckconf.cache_dir(), "workspace-notes-seen.json")

def watch_notes(sess):
    """Mark a workspace's tab (tabmark.bump -- the same mechanism #26 built
    for `phosphor notify` and mentions) the moment its NOTES.md's mtime
    moves: the notebook is the only channel a workspace's assistants (or a
    human) have to hand work to each other, and until now nothing signalled
    a new entry landed there -- you only found out by polling it by hand.
    Runs from mentions.marker()'s always-on loop, same 3s cadence as its
    other tab-marking work. First sight of a workspace just remembers its
    current mtime as the baseline: a fresh deck (or a workspace nobody's
    watched yet) never floods every tab with history that predates it."""
    seen = {}
    try:
        with open(NOTES_SEEN) as f:
            seen = json.load(f)
        if not isinstance(seen, dict): seen = {}
    except (OSError, ValueError):
        pass
    import tabmark
    r, changed = root(), False
    for name in names():
        try:
            mtime = os.path.getmtime(os.path.join(r, name, "NOTES.md"))
        except OSError:
            continue
        prev = seen.get(name)
        seen[name] = mtime
        if prev is None:
            changed = True; continue
        if mtime > prev:
            tabmark.bump(sess, name.upper())
            changed = True
    if changed:
        os.makedirs(os.path.dirname(NOTES_SEEN), exist_ok=True)
        open(NOTES_SEEN, "w").write(json.dumps(seen))

def main():
    argv = sys.argv[1:]
    sub = argv[0] if argv else "list"
    if sub == "new":
        pause = "--pause-on-error" in argv            # the + menu: its tab would vanish with the error
        rc = new([x for x in argv[1:] if x != "--pause-on-error"])
        if rc and pause and sys.stdin.isatty():
            try: input("  " + DIM + "Enter closes this tab" + RST)
            except (EOFError, KeyboardInterrupt): pass
        return rc
    if sub == "open" and len(argv) > 1:
        open_tab(slug(argv[1])); return 0
    if sub == "list":
        return listing()
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main() or 0)
