"""phosphor notes — a shared notebook between you and your assistants.

Plain Markdown at ~/.local/share/phosphor/notes.md (override: PHOSPHOR_NOTES),
or inside a folder you already sync -- Obsidian, Syncthing, git -- with
`[notes] folder` in the profile. Anyone who can run a shell command can
write to it — you, a script, an AI:

    phosphor note "text"                          quick note
    phosphor note --kind decision "text"          note idea decision todo summary
    phosphor note --by claude --kind summary -    body from stdin, 1st line = title
    phosphor note --tab SYS "text"                where it came from
    phosphor note --project NAME "text"           which project it's about
    phosphor note --here                          ask for it, tagged with this tab (Alt-j)

A note can say which tab it was taken from (`me @SYS` in its header):
the tab shows it, and f narrows the list to one tab (`phosphor notes --tab SYS`).
A note can also belong to a project (`#NAME` in its header): written from a
workspace's folder or tab it takes that workspace's name by itself, and the
tab folds each project's notes into a folder (m moves a note to another).

`phosphor notes` shows it newest first and reloads when the file changes.
In the tab a note can be picked (tap, j/k) and then edited, archived, marked
done or talked over with an assistant. Archived notes go to notes-archive.md
(`phosphor notes --archive`), where they can be restored or deleted for good.
"""
import fcntl, os, re, shlex, shutil, subprocess, sys, tempfile, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

def notes_conf():
    import deckconf
    try: return (deckconf.load()[0] or {}).get("notes") or {}
    except Exception: return {}

def notes_dir():
    """Where the notebook lives: the profile's `[notes] folder` if set (a
    vault you already sync), else the private default under ~/.local/share."""
    import deckconf
    folder = notes_conf().get("folder")
    return os.path.expanduser(folder) if folder else deckconf.data_dir()

PATH = DEFAULT_PATH = os.environ.get("PHOSPHOR_NOTES") or os.path.join(notes_dir(), "notes.md")
BOOK = "NOTES"
ARCHIVE_VIEW = False
ONLY_TAB = None           # --tab: only the notes taken from that tab
ONLY_PROJECT = None       # --project: notes, only that project's; note, filed under it
FOLDERS = False           # the tab is showing projects as folders (render leaves #NAME out)
WORKSPACES = []           # the workspaces' names: their folders are marked in the tab
REQUIRED = notes_conf().get("require_project") is True   # [notes] require_project

def required():
    """Every new note in the deck's own notebook needs a project: --file and
    --book are someone else's notebook, with rules of their own."""
    return REQUIRED and PATH == DEFAULT_PATH

def workspaces():
    try:
        import workspace
        return workspace.names()
    except Exception:
        return []

def project_choices(first=""):
    """What Tab offers for a project: the guess, the ones in use (newest
    first), then the workspaces nothing is filed under yet."""
    out = [first] if first else []
    for n in projects_in(PATH) + workspaces():
        if n not in out: out.append(n)
    return out

def migrate(old_path, new_path):
    """Move a notebook (and its archive) to a new folder, only the files
    that don't already exist there: never merges, never overwrites."""
    moved = []
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    for src, dst in ((old_path, new_path), (archive_of(old_path), archive_of(new_path))):
        if os.path.exists(src) and not os.path.exists(dst) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.move(src, dst)
            moved.append(os.path.basename(dst))
    return moved

# A few places a synced vault typically lives; used only to offer folders
# that already look like an Obsidian vault, never to read what's in them.
VAULT_ROOTS = ("~", "~/Documents", "~/Obsidian", "~/obsidian", "~/Sync", "~/sync",
               "~/Dropbox", "~/OneDrive")

def vault_candidates():
    """Folders one level under a few common roots that have `.obsidian/`.
    Best-effort and non-exhaustive: an empty list just means the only way
    in is typing a path."""
    seen, out = set(), []
    for root in VAULT_ROOTS:
        base = os.path.expanduser(root)
        if not os.path.isdir(base): continue
        try: names = sorted(os.listdir(base))
        except OSError: continue
        for n in names:
            p = os.path.join(base, n)
            if p in seen or n.startswith(".") or not os.path.isdir(p): continue
            if os.path.isdir(os.path.join(p, ".obsidian")):
                seen.add(p); out.append(p)
    return out

def choose_folder(current):
    """Ask where the notebook should live: private, an existing vault-like
    folder, or a typed path. Returns a folder, or None for private."""
    from init import ask, pick
    cands = vault_candidates()
    home = os.path.expanduser("~")
    opts = ["private (~/.local/share/phosphor)"] + \
           [c.replace(home, "~", 1) + "  " + DIM + "(has .obsidian)" + RST for c in cands] + \
           ["type a path"]
    default = 0
    if current:
        cur = os.path.expanduser(current)
        default = 1 + cands.index(cur) if cur in cands else len(opts) - 1
    i = pick("where should the notebook live?", opts, default)
    if i == 0: return None
    if i == len(opts) - 1:
        p = ask("folder (created if it doesn't exist)", current or "")
        return os.path.expanduser(p) if p.strip() else None
    return cands[i - 1]

def use_book(argv):
    """--book NAME switches to NAME.md next to the main notebook (e.g. work);
    --file PATH any notebook file; --archive shows that book's archive."""
    global PATH, BOOK, ARCHIVE_VIEW, ONLY_TAB, ONLY_PROJECT
    if "--book" in argv:
        i = argv.index("--book")
        name = argv[i + 1] if i + 1 < len(argv) else "notes"
        del argv[i:i + 2]
        PATH = os.path.join(notes_dir(), "%s.md" % name)
        BOOK = (name.upper() + " NOTES") if name != "notes" else "NOTES"
    if "--file" in argv:                     # any notebook, e.g. a workspace's NOTES.md
        i = argv.index("--file")
        PATH = os.path.abspath(os.path.expanduser(argv[i + 1] if i + 1 < len(argv) else "NOTES.md"))
        del argv[i:i + 2]
        BOOK = os.path.basename(os.path.dirname(PATH)).upper() + " NOTES"
    if "--tab" in argv:                      # notes: only that tab's; note: taken from it
        i = argv.index("--tab")
        ONLY_TAB = clean_tab(argv[i + 1] if i + 1 < len(argv) else "") or None
        del argv[i:i + 2]
    if "--project" in argv:                  # "" (no project) is a project of its own here
        i = argv.index("--project")
        ONLY_PROJECT = clean_project(argv[i + 1] if i + 1 < len(argv) else "")
        del argv[i:i + 2]
    if "--archive" in argv:
        argv.remove("--archive")
        ARCHIVE_VIEW = True
        BOOK += " ARCHIVE"
    return argv

def archive_of(path):
    return re.sub(r"\.md$", "", path) + "-archive.md"

PREAMBLE = "# Phosphor notes\n\nShared notebook: you and your assistants write here.\n\n"

class locked:
    """Every writer takes this lock: an assistant appending while the tab
    rewrites the file would otherwise lose its note."""
    def __init__(self, path): self.path = path + ".lock"
    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.f = open(self.path, "a"); fcntl.flock(self.f, fcntl.LOCK_EX); return self
    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()

def clean_tab(tab):
    return re.sub(r"[·@\n]", " ", tab or "").strip()

def clean_project(p):
    """One word, so Obsidian reads `#NAME` in the header as a tag too."""
    return re.sub(r"\s+", "-", re.sub(r"[·@#\n]", " ", p or "").strip())

def header(when, kind, by, title, tab="", project=""):
    tab, project = clean_tab(tab), clean_project(project)
    return "## %s · %s · %s%s%s · %s" % (when, kind, by.strip(), " @" + tab if tab else "",
                                         " #" + project if project else "", title)

def append(path, kind, by, title, body="", tab="", project=""):
    """One entry at the end of a notebook (created with its header if new)."""
    with locked(path):
        fresh = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if fresh:
                f.write(PREAMBLE)
            f.write(header(time.strftime("%Y-%m-%d %H:%M"), kind, by, title, tab, project) + "\n")
            if body:
                f.write("\n" + body + "\n")
            f.write("\n")
KINDS = {"note": FG, "idea": BLOOM, "decision": AMB, "todo": RED, "summary": PH, "done": MUTE}
ENTRY = re.compile(r"^## (\S+ \S+) · (\w+) · ([^·]+?)(?: · (.*))?$")
STRIP = re.compile(r"\x1b\[[0-9;]*m")

def add(argv):
    args, kind, by = use_book(list(argv)), "note", os.environ.get("USER", "me")
    def take(flag):
        if flag in args:
            i = args.index(flag)
            v = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
            return v
    kind = take("--kind") or kind
    by = take("--by") or by
    tab = ONLY_TAB or ""
    project = ONLY_PROJECT if ONLY_PROJECT is not None else guess_project(tab or None)
    if "--here" in args:
        return here(kind if kind != "note" else None)
    if required() and not project:
        ws = workspaces()
        print("a note needs a project here ([notes] require_project): --project NAME")
        used = projects_in(PATH)
        if used: print("  in use:     " + " ".join(used))
        if ws: print("  workspaces: " + " ".join(ws))
        return 2
    if kind not in KINDS:
        print("unknown kind %r — use one of: %s" % (kind, ", ".join(KINDS))); return 1
    if args in ([], ["-"]) and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        text = " ".join(a for a in args if a != "-").strip()
    if not text:
        print('usage: phosphor note [--kind K] [--by NAME] "text"   (- reads stdin)'); return 1
    lines = text.splitlines()
    title, body = lines[0].strip(), "\n".join(lines[1:]).strip()
    append(PATH, kind, by, title, body, tab, project)
    return 0

def guess_project(tab=None):
    """The workspace a note is written from, by its folder (an assistant in
    it) or its tab (Alt-j there); else the project the last note from that
    tab went to; else "". Only for the deck's own notebook: --file and
    --book already say where a note goes."""
    if PATH != DEFAULT_PATH: return ""
    try:
        import workspace
        names, root = workspace.names(), os.path.realpath(workspace.root())
        rel = os.path.relpath(os.path.realpath(os.getcwd()), root).split(os.sep)[0]
        if rel in names: return rel
    except Exception:
        names = []
    tab = this_tab() if tab is None else tab
    if not tab: return ""
    return next((n for n in names if n.upper() == tab.upper()), "") \
        or next((e["project"] for e in entries(PATH, tab=tab) if e["project"]), "")

# --- the file as blocks: each entry's raw text, so a change touches only that entry

def split(text):
    """(preamble, [raw entry text]) in file order, oldest first."""
    pre, blocks = [], []
    for line in text.splitlines():
        if ENTRY.match(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            pre.append(line)
    return "\n".join(pre), ["\n".join(b).strip("\n") for b in blocks]

def parse(raw):
    lines = raw.splitlines()
    m = ENTRY.match(lines[0])
    body = lines[1:]
    while body and not body[-1].strip(): body.pop()
    while body and not body[0].strip(): body.pop(0)
    by, sep, project = m.group(3).strip().rpartition(" #")
    if not sep: by, project = project, ""
    by, _, tab = by.rpartition(" @")
    if not by: by, tab = tab, ""
    return {"when": m.group(1), "kind": m.group(2), "by": by.strip(), "tab": tab.strip(),
            "project": project.strip(), "title": m.group(4) or "", "body": body, "raw": raw}

def read(path):
    try:
        # never the locale's encoding, and a broken byte (a write still
        # landing, a hand edit) is one odd character, not a crashed tab
        with open(path, encoding="utf-8", errors="replace") as f:
            return split(f.read())
    except FileNotFoundError:
        return "", []

def write(path, pre, blocks):
    pre = pre.strip("\n")
    text = (pre + "\n\n" if pre else PREAMBLE) + "".join(b + "\n\n" for b in blocks)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def entries(path=None, tab=None, project=None):
    """Newest first; project="" is the notes with no project."""
    out = [parse(b) for b in read(path or PATH)[1]][::-1]
    if tab: out = [e for e in out if e["tab"] == tab]
    return out if project is None else [e for e in out if e["project"] == project]

def projects_in(path=None):
    """The projects notes are filed under, most recent first."""
    seen = []
    for e in entries(path):
        if e["project"] and e["project"] not in seen: seen.append(e["project"])
    return seen

def tabs_in(path=None):
    """The tabs notes were taken from, most recent first."""
    seen = []
    for e in entries(path):
        if e["tab"] and e["tab"] not in seen: seen.append(e["tab"])
    return seen

def rekind(raw, kind=None, by=None, title=None, body=None, project=None):
    e = parse(raw)
    out = header(e["when"], kind or e["kind"], by or e["by"], e["title"] if title is None else title,
                 e["tab"], e["project"] if project is None else project)
    b = e["body"] if body is None else body
    return out + ("\n\n" + "\n".join(b) if b else "")

def replace(path, raw, new):
    """Swap one entry's text; False if it isn't there any more."""
    with locked(path):
        pre, blocks = read(path)
        if raw not in blocks: return False
        blocks[blocks.index(raw)] = new
        write(path, pre, blocks)
        return True

DONE_AT = re.compile(r"^done \d{4}-\d\d-\d\d \d\d:\d\d$")

def done_at(e):
    """When a done todo was marked done ("YYYY-MM-DD HH:MM", its last body
    line, written by archive()), or None: its header keeps the day it was
    written, not the day it was done."""
    return e["body"][-1][5:] if e["body"] and DONE_AT.match(e["body"][-1]) else None

def archive(path, raw, done=False):
    """Move an entry to the archive (a todo marked done on the way, with
    when as its last line)."""
    new = rekind(raw, kind="done", body=parse(raw)["body"] + ["", "done " + time.strftime("%Y-%m-%d %H:%M")]) \
        if done else raw
    with locked(path):
        pre, blocks = read(path)
        if raw not in blocks: return False
        blocks.remove(raw)
        apre, ablocks = read(archive_of(path))
        write(archive_of(path), apre, ablocks + [new])
        write(path, pre, blocks)
        return True

def restore(path, raw=None):
    """Put an archived entry back where its date puts it (the last archived one
    by default). A done todo comes back as a todo. Returns its title or None."""
    with locked(path):
        apre, ablocks = read(archive_of(path))
        if not ablocks or (raw is not None and raw not in ablocks): return None
        raw = raw if raw is not None else ablocks[-1]
        ablocks.remove(raw)
        e = parse(raw)
        if e["kind"] == "done":
            body = e["body"][:-1] if done_at(e) else e["body"]
            while body and not body[-1].strip(): body = body[:-1]
            back = rekind(raw, kind="todo", body=body)
        else:
            back = raw
        pre, blocks = read(path)
        at = next((i for i, b in enumerate(blocks) if parse(b)["when"] > e["when"]), len(blocks))
        blocks.insert(at, back)
        write(path, pre, blocks)
        write(archive_of(path), apre, ablocks)
        return e["title"] or "(untitled)"

def forget(path, raw):
    """Delete an archived entry for good."""
    with locked(path):
        apre, ablocks = read(archive_of(path))
        if raw not in ablocks: return False
        ablocks.remove(raw)
        write(archive_of(path), apre, ablocks)
        return True

def edited(raw, text, me):
    """The entry rewritten from the editor's text (1st line = title). Someone
    else's note gets marked, so its author knows the words aren't theirs."""
    lines = text.strip("\n").splitlines()
    if not lines or not lines[0].strip(): return None
    e = parse(raw)
    by = e["by"]
    if by != me and "edited by" not in by:
        by += ", edited by " + me
    body = "\n".join(lines[1:]).strip("\n").splitlines()
    new = rekind(raw, by=by, title=lines[0].strip(), body=body)
    # nothing changed: keep the raw text (and the author) as they were
    return raw if parse(new)["title"] == e["title"] and parse(new)["body"] == e["body"] else new

# --- the tab

def folded(notes, closed, everything=False):
    """The tab's rows: each project a folder (its count, Enter opens it) with
    its notes under it when open. No project comes first and starts open, the
    rest by their newest note and start closed: closed holds what the reader
    toggled away from that. A notebook with no projects stays a plain list."""
    groups = {}
    for e in notes: groups.setdefault(e["project"], []).append(e)
    if not any(groups): return list(notes)
    out = []
    for name in sorted(groups, key=lambda n: n != ""):          # stable: newest first after ""
        is_open = everything or ((name == "") != (name in closed))
        out.append({"folder": name, "count": len(groups[name]), "open": is_open})
        if is_open: out += groups[name]
    return out

def render(w, notes):
    """Lines, plus the row index each line belongs to (a note or a folder)."""
    lines, owner, ww = [], [], max(20, w - 4)
    for i, e in enumerate(notes):
        def put(s): lines.append(s); owner.append(i)
        if "folder" in e:
            ws = e["folder"] in WORKSPACES
            put(AMB + ("▾ " if e["open"] else "▸ ") + (e["folder"] or "no project") + RST
                + DIM + "  %d" % e["count"] + RST
                + (DIM + "  · " + RST + PH + "workspace" + RST if ws else "")
                + (DIM + "  · m files each one" + RST if not e["folder"] and required() else ""))
            continue
        put(KINDS.get(e["kind"], FG) + e["kind"].upper() + RST
            + DIM + "  " + e["when"] + " · " + e["by"] + RST
            + (DIM + " · from " + RST + PH + e["tab"] + RST if e["tab"] else "")
            + (DIM + " · #" + e["project"] + RST if e["project"] and not FOLDERS else ""))
        for t in textwrap.wrap(e["title"], ww) or []:
            put("  " + BLOOM + t + RST)
        for b in e["body"]:
            for t in textwrap.wrap(b, ww, subsequent_indent="  " if b.lstrip().startswith("-") else "") or [""]:
                put("  " + FG + t + RST)
        put(RULE + "─" * min(w - 2, 60) + RST)
    if not lines:
        empty = "The archive is empty." if ARCHIVE_VIEW else 'No notes yet.  phosphor note "..." adds one.'
        if ONLY_TAB and not ARCHIVE_VIEW: empty = "No notes from %s.  f shows every tab." % ONLY_TAB
        return [DIM + empty + RST], [None]
    return lines, owner

# --- writing a note: a small editor of our own. input() loses its place when a
# line wraps on a narrow screen, and a phone keyboard sends whole words at once.

PASTE_ON, PASTE_OFF = "\x1b[200~", "\x1b[201~"
SEQ = re.compile(r"\x1b\[[0-9;<?]*[~A-Za-z]|\x1bO.|\x1b.?", re.S)

def tokens(s, pasting=False):
    """(what was typed, as tokens, still inside a paste?). A token is a
    printable character, a control character, an escape sequence, or "PASTE_NL"
    for a line break inside a paste (it never saves)."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "\x1b":
            m = SEQ.match(s, i)
            seq = m.group(0)
            if seq == PASTE_ON: pasting = True
            elif seq == PASTE_OFF: pasting = False
            else: out.append(seq)
            i += len(seq)
            continue
        c = s[i]
        if pasting and c in "\r\n":
            if not (c == "\n" and i and s[i - 1] == "\r"):
                out.append("PASTE_NL")
        else:
            out.append(c)
        i += 1
    return out, pasting

def typed(lines, tok):
    """One token applied to the note being written: (lines, None | "save" | "cancel")."""
    lines = list(lines) or [""]
    if tok == "\x03":
        return lines, "cancel"
    if tok in ("\r", "\n"):
        if not lines[-1].strip():
            return [l for l in lines if l.strip()] or [""], "save"
        return lines + [""], None
    if tok == "PASTE_NL":
        return lines + [""], None
    if tok in ("\x7f", "\x08"):
        if lines[-1]: lines[-1] = lines[-1][:-1]
        elif len(lines) > 1: lines.pop()
        return lines, None
    if tok == "\x15":                                  # Ctrl-u: the whole line
        lines[-1] = ""
        return lines, None
    if len(tok) == 1 and (tok == "\t" or tok >= " "):
        lines[-1] += " " if tok == "\t" else tok
    return lines, None

def draw_note(kind, tab, lines, w, project="", asking=None):
    """The screen while writing: what it is, one hint, and the text wrapped by
    us. asking: (what's typed, the choices) while it asks for the project."""
    tw = max(10, w - 4)
    out = ["  " + KINDS.get(kind, FG) + "new " + kind + RST
           + (DIM + " from " + RST + PH + tab + RST if tab else "")
           + (DIM + " · #" + RST + PH + project + RST if project and asking is None else ""),
           "  " + DIM + ("Enter: a new line · Enter on an empty line saves · Ctrl-c cancels"
                         if w >= 72 else "Enter twice saves · Ctrl-c cancels") + RST, ""]
    if asking is not None:
        q, choices = asking
        out[1] = "  " + DIM + "Enter files it · Tab: another · Esc: back to the text" + RST
        for l in lines[:1]: out.append("  " + BLOOM + l[:tw] + RST)
        out += ["", "  " + PH + "project: " + RST + q]
        row = len(out)
        marks = ["◆" + c if c in WORKSPACES else c for c in choices[:8]]
        for t in textwrap.wrap(" ".join(marks), tw)[:3]: out.append("  " + DIM + t + RST)
        if any(c in WORKSPACES for c in choices[:8]):
            out.append("  " + DIM + "◆ a workspace" + RST)
        return out, row, 12 + len(q)
    for n, l in enumerate(lines):
        parts = [l[i:i + tw] for i in range(0, len(l), tw)] or [""]
        if len(l) and len(l) % tw == 0 and n == len(lines) - 1:
            parts.append("")                           # the cursor goes to the next row
        for j, part in enumerate(parts):
            lead = (PH + "> " + RST) if n == 0 and j == 0 else "  "
            out.append("  " + lead + (BLOOM if n == 0 else FG) + part + RST)
    if len(lines) > 1 and not lines[-1] and any(l.strip() for l in lines):
        out.append("  " + DIM + "  Enter again saves" + RST)
        cur_row = len(out) - 1                         # cursor on the empty line above the hint
    else:
        cur_row = len(out)
    col = 5 + (len(lines[-1]) % tw if lines[-1] and len(lines[-1]) % tw else 0)
    return out, cur_row, col

def asked(q, at, choices, tok):
    """One key while asking for the project: (q, at, None | "file" | "back")."""
    if tok in ("\r", "\n"): return q, at, ("file" if clean_project(q) else None)
    if tok == "\x03" or tok == "\x1b": return q, at, "back"
    if tok == "\t" and choices:
        at = (at + 1) % len(choices); return choices[at], at, None
    if tok in ("\x7f", "\x08"): return q[:-1], at, None
    if tok == "\x15": return "", at, None
    if len(tok) == 1 and tok >= " " and tok not in "·@#": return q + tok, at, None
    return q, at, None

def compose(kind="note", tab="", project=""):
    """Write a note from inside the tab: no other tool, no other tab.
    With [notes] require_project, saving asks which project it goes to
    (the guess already typed: Enter files it). True when something was saved."""
    global WORKSPACES
    WORKSPACES = workspaces()
    choices = project_choices(project) if required() else []
    asking = None                                      # [q, at] while asking for the project
    fd = sys.stdin.fileno()
    import select, termios, tty
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?2004h"); sys.stdout.flush()
    # a tap brought us here: its release is still on its way, and would
    # land in the note as text
    time.sleep(0.15)
    old = termios.tcgetattr(fd)
    lines, done, pasting = [""], None, False
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
        tty.setraw(fd)
        while done is None:
            w = shutil.get_terminal_size((70, 24)).columns
            out, row, col = draw_note(kind, tab, lines, w, project,
                                      None if asking is None else (asking[0], choices))
            sys.stdout.write("\x1b[H\x1b[J" + "\r\n".join(out) + "\x1b[%d;%dH" % (row, col))
            sys.stdout.flush()
            if not select.select([fd], [], [], 1.0)[0]:
                continue
            data = os.read(fd, 4096)
            while select.select([fd], [], [], 0.01)[0] and len(data) < 65536:
                data += os.read(fd, 4096)              # the rest of a paste
            toks, pasting = tokens(data.decode("utf-8", "replace"), pasting)
            for t in toks:
                if asking is not None:
                    asking[0], asking[1], what = asked(asking[0], asking[1], choices, t)
                    if what == "back": asking = None; lines = lines + [""]
                    elif what == "file": project, done = clean_project(asking[0]), "save"; break
                    continue
                lines, done = typed(lines, t)
                if done == "save" and required() and any(l.strip() for l in lines):
                    asking, done = [project, -1], None
                if done: break
    except KeyboardInterrupt:
        done = "cancel"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\x1b[?2004l\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()
    saved = done == "save" and any(l.strip() for l in lines)
    if saved:
        append(PATH, kind, os.environ.get("USER", "me"), lines[0].strip(),
               "\n".join(lines[1:]).strip(), tab, project)
    return saved

def this_tab():
    """The name of the tab this pane is in (without edit's pencil), or ""."""
    import json, newtab
    me = os.environ.get("ZELLIJ_PANE_ID")
    if not me: return ""
    try:
        ps = json.loads(newtab.zj("list-panes", "-a", "-j") or "[]")
    except ValueError:
        return ""
    mine = next((p for p in ps if not p.get("is_plugin") and str(p.get("id")) == me), None)
    return (mine or {}).get("tab_name", "").replace(" ✎", "").strip()

def here(kind=None):
    """What the note key runs over the pane you're in: pick a kind (a key or
    a tap), write it, and it's saved tagged with this tab. Then it's gone."""
    tab = this_tab()
    kinds = [("n", "note"), ("t", "todo"), ("i", "idea")]
    if kind is None:
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
        try:
            while kind is None:
                sys.stdout.write("\x1b[2J\x1b[H\n  " + BLOOM + "a note" + RST
                                 + (DIM + " from " + RST + PH + tab + RST if tab else "") + "\n\n")
                for n, (k, name) in enumerate(kinds):
                    sys.stdout.write("   " + AMB + k + RST + "  " + KINDS[name] + name + RST + "\n\n")
                sys.stdout.write("   " + DIM + "Enter: note · q: never mind" + RST)
                sys.stdout.flush()
                k = getkey(None, mouse=True)
                if isinstance(k, tuple):             # a tap on a row (rows 4, 6, 8)
                    row = k[2]
                    k = kinds[(row - 4) // 2][0] if row in (4, 6, 8) else None
                if k in ("q", "\x03", "\x1b"): return 0
                if k in ("\r", "\n"): k = "n"
                kind = dict(kinds).get(k)
        finally:
            sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h"); sys.stdout.flush()
    saved = compose(kind, tab, guess_project(tab))
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[2J\x1b[H"); sys.stdout.flush()
    if saved:
        print("\n  " + PH + "saved" + RST + DIM + " in %s%s" % (BOOK, " · from " + tab if tab else "") + RST)
        time.sleep(1)
    return 0

def edit(e):
    """The note in $EDITOR: first line the title, the rest the body."""
    me = os.environ.get("USER", "me")
    fd, tmp = tempfile.mkstemp(prefix="phosphor-note-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(e["title"] + "\n" + ("\n" + "\n".join(e["body"]) + "\n" if e["body"] else ""))
    import deckconf
    cmd = shlex.split(deckconf.editor(deckconf.load()[0], ask_login=False))
    if not cmd or not deckconf.exe(cmd[0]):
        cmd = [next((x for x in ("nano", "vi") if shutil.which(x)), "vi")]
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h"); sys.stdout.flush()
    try:
        subprocess.call(cmd + [tmp])
        new = edited(e["raw"], open(tmp, encoding="utf-8", errors="replace").read(), me)
    finally:
        os.unlink(tmp)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()
    if new is None: return "empty title: left as it was"
    if new == e["raw"]: return "no changes"
    return "saved" if replace(PATH, e["raw"], new) else "the note changed meanwhile: not saved"

# Assistants that take a first message and stay open: the same ones a
# workspace starts (aichat answers once and exits, so it isn't one of them).
from workspace import FIRST, assistant_first_cmd
CHATS = list(FIRST.items())

def chat(e):
    """A new tab where an assistant starts from this note."""
    import deckconf, gen, newtab
    if not os.environ.get("ZELLIJ"):
        return "chat opens a tab: only inside the deck"
    found = next((b for b, _ in CHATS if newtab.have(b)), None)
    if not found:
        return "no assistant installed: " + ", ".join(b for b, _ in CHATS)
    d = os.path.join(deckconf.cache_dir(), "chat")
    os.makedirs(d, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    brief = os.path.join(d, stamp + ".md")
    with open(brief, "w") as f:
        f.write("This is a note from my Phosphor notebook (%s). I want to talk it over "
                "before doing anything: don't change files yet.\n\n%s\n" % (PATH, e["raw"]))
    prof, _ = deckconf.load()
    line = assistant_first_cmd(found, "\"$(cat %s)\"" % shlex.quote(brief))
    tab = {"name": "CHAT", "panes": [{"cmd": "bash", "args": ["-lc", line]}]}
    lay = os.path.join(d, stamp + ".kdl")
    with open(lay, "w") as f:
        f.write(gen.tab_kdl(tab, gen.Ctx(prof or {}), "phosphor notes (chat)"))
    name = newtab.unique("CHAT", newtab.taken_names())
    newtab.zj("new-tab", "--layout", lay, "--name", name)
    return "opened " + name + " with " + found

def to_workspace(e):
    """A workspace from this note, after showing which note it is."""
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    w = min(shutil.get_terminal_size((70, 24)).columns, 90) - 4
    print("  " + BLOOM + "A workspace from this note" + RST + "\n")
    print("  " + KINDS.get(e["kind"], FG) + e["kind"].upper() + RST + DIM + "  " + e["when"] + " · " + e["by"] + RST)
    for t in textwrap.wrap(e["title"], w): print("  " + BLOOM + t + RST)
    for b in e["body"][:4]:
        for t in textwrap.wrap(b, w)[:1]: print("  " + FG + t + RST)
    if len(e["body"]) > 4: print("  " + DIM + "..." + RST)
    print()
    try:
        ok = input("  " + BLOOM + "? " + RST + "is this the note? " + DIM + "(Y/n) " + RST).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ok = "n"
    msg = "left as it was"
    if ok in ("", "y", "yes", "s", "si", "sí"):
        fd, tmp = tempfile.mkstemp(prefix="phosphor-note-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(e["raw"] + "\n")
        env = dict(os.environ, PHOSPHOR_NOTES=PATH)
        try:
            r = subprocess.call([sys.executable, os.path.join(REPO, "phosphor"), "workspace", "new",
                                 "--note-file", tmp], env=env)
        except KeyboardInterrupt:
            r = 1
        finally:
            os.unlink(tmp)
        if r != 0:
            try: input("  " + DIM + "Enter to go back" + RST)
            except (EOFError, KeyboardInterrupt): pass
        msg = "workspace opened" if r == 0 else "no workspace"
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()
    return msg

def actions(e):
    """Every key, always in the same place: [(key, label, usable now)]. The
    ones that need a picked note (or a todo) are dimmed until they apply."""
    if ARCHIVE_VIEW:
        return [("r", "restore", bool(e)), ("D", "delete for good", bool(e)), ("q", "quit", True)]
    return [("e", "edit", bool(e)), ("d", "archive", bool(e)),
            ("x", "done", bool(e) and e["kind"] == "todo"), ("c", "chat", bool(e)),
            ("w", "workspace", bool(e)), ("m", "move", bool(e)),
            ("a", "write", True), ("t", "todo", True), ("i", "idea", True), ("u", "undo", True),
            ("f", "from: " + (ONLY_TAB or "every tab"), True), ("/", "search", True)]

def footer(acts, w):
    """Footer lines and where each key sits: [(line, first col, last col, key)]."""
    lines, spots, cur, x = [], [], " ", 2
    for k, label, on in acts:
        item = k + " " + label
        if x > 2 and x + 3 + len(item) > w:
            lines.append(cur); cur, x = " ", 2
        if x > 2:
            cur += DIM + " · " + RST; x += 3
        if on: spots.append((len(lines), x, x + len(item) - 1, k))
        cur += (AMB + k + RST + DIM if on else MUTE + k) + " " + label + RST; x += len(item)
    lines.append(cur)
    return lines, spots

def confirm(q, rows):
    sys.stdout.write("\x1b[%d;1H\x1b[K " % rows + RED + q[:60] + "? " + RST + DIM + "y / n " + RST)
    sys.stdout.flush()
    return getkey(None, mouse=True) == "y"

def matches(e, q):
    q = q.lower()
    return any(q in "\n".join(v if isinstance(v, list) else [v or ""]).lower()   # body is a list of lines
               for v in (e.get(f) for f in ("title", "body", "by", "tab", "project")))

def search_prompt(rows, current, label="/", choices=(), marked=()):
    """A one-line prompt on the footer's row. Returns the new query (empty
    clears it), or None if cancelled -- the query stays whatever it was.
    Tab steps through choices, when there are any; the marked ones show a ◆
    (workspaces, among projects)."""
    q, at = current, -1
    while True:
        hint = DIM + "   Tab: " + " ".join(("◆" if c in marked else "") + c for c in choices) + RST if choices else ""
        sys.stdout.write("\x1b[%d;1H\x1b[K " % rows + PH + label + RST + q + hint + "\x1b[K")
        sys.stdout.flush()
        k = getkey(None, mouse=True)
        if k is None or isinstance(k, tuple):
            continue
        if k in ("\r", "\n"): return q
        if k in ("\x03", "\x1b"): return None
        if k == "\t" and choices:
            at = (at + 1) % len(choices); q = choices[at]
        elif k in ("\x7f", "\x08"): q = q[:-1]
        elif k == "\x15": q = ""                          # Ctrl-u
        elif len(k) == 1 and k >= " ": q += k

def move(e, rows):
    """m: file a note under a project (Tab offers the ones in use and the
    workspaces; empty: no project)."""
    p = search_prompt(rows, e["project"], "project: ", project_choices(), set(WORKSPACES))
    if p is None: return ""
    p = clean_project(p)
    if p == e["project"]: return "no changes"
    if not p and required(): return "a note needs a project here: not moved"
    if not replace(PATH, e["raw"], rekind(e["raw"], project=p)):
        return "the note changed meanwhile: not moved"
    return ("moved to " + p) if p else "no project now"

def main():
    global ONLY_TAB, FOLDERS, WORKSPACES
    use_book(sys.argv)
    view = archive_of(PATH) if ARCHIVE_VIEW else PATH
    if not sys.stdin.isatty():                       # piped: plain dump
        try:
            for l in render(78, entries(view, ONLY_TAB, ONLY_PROJECT))[0]: print(STRIP.sub("", l))
        except BrokenPipeError:                      # | head
            sys.stdout = None
        return 0
    st = {"off": 0, "sel": None, "msg": "", "msg_t": 0, "mt": None, "q": ""}
    lastw, lastq, notes, lines, owner = None, None, [], [], []
    closed = set()                                   # folders toggled from how they start
    def ident(r): return r["raw"] if "raw" in r else ("folder", r["folder"])
    def say(s):
        st.update(msg=s, msg_t=time.time(), mt=None)   # mt=None: reload now
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((70, 24))
            w = min(cols, 100)
            try: cur = os.path.getmtime(view)
            except OSError: cur = 0
            if cur != st["mt"] or w != lastw or st["q"] != lastq:   # reload on change, resize or search
                sel = st["sel"]
                picked = ident(notes[sel]) if sel is not None and sel < len(notes) else None
                found = entries(view, None if ARCHIVE_VIEW else ONLY_TAB, ONLY_PROJECT)
                WORKSPACES = workspaces()
                if st["q"]: found = [n for n in found if matches(n, st["q"])]
                # one project asked for: no folders; a search opens every one it reaches
                notes = list(found) if ONLY_PROJECT is not None else folded(found, closed, bool(st["q"]))
                FOLDERS = len(notes) != len(found)
                lines, owner = render(w - 2, notes)
                st["mt"], lastw, lastq = cur, w, st["q"]
                raws = [ident(n) for n in notes]
                if picked in raws: st["sel"] = raws.index(picked)
                elif sel is not None and notes: st["sel"] = min(sel, len(notes) - 1)
                else: st["sel"] = None
            sel = st["sel"]
            folder = notes[sel] if sel is not None and "folder" in notes[sel] else None
            e = notes[sel] if sel is not None and not folder else None
            foot, spots = footer(actions(e), w)
            body = max(3, rows - 2 - len(foot))
            maxoff = max(0, len(lines) - body)
            off = st["off"] = max(0, min(st["off"], maxoff))
            if time.time() - st["msg_t"] > 5: st["msg"] = ""
            sub = " · ".join(x for x in (("from " + ONLY_TAB) if ONLY_TAB and not ARCHIVE_VIEW else "",
                                         ("#" + (ONLY_PROJECT or "no project")) if ONLY_PROJECT is not None else "",
                                         ("search: " + st["q"]) if st["q"] else "") if x)
            right = st["msg"] or ("%d entries · Enter opens or closes it" % len(found) if folder
                                  else ("%d entries · tap one or j to pick" if found and not e
                                        else "%d entries · newest first") % len(found))
            out = topbar(BOOK, sub, right, w)
            win = range(off, min(off + body, len(lines)))
            for i in win:
                mark = AMB + "▌" + RST if sel is not None and owner[i] == sel else " "
                out.append(mark + pad(lines[i], w - 2))
            out += [""] * (body - len(win))
            first_foot = len(out) + 1                # screen row (1-based) of the footer
            out += foot
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out[:rows]) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            k = getkey(1.0, mouse=True)
            if k is None: continue
            if isinstance(k, tuple):
                col, row = k[1], k[2]
                if row >= first_foot:
                    hit = [s for s in spots if s[0] == row - first_foot and s[1] <= col <= s[2]]
                    if not hit: continue
                    k = hit[0][3]
                elif HEAD < row <= HEAD + body:
                    i = off + row - HEAD - 1
                    if i < len(owner) and owner[i] is not None:
                        st["sel"] = owner[i]
                        if "folder" in notes[owner[i]]:            # a tap on a folder opens it
                            closed ^= {notes[owner[i]]["folder"]}; st["mt"] = None
                    continue
                else:
                    continue
            def show(i):
                rows_of = [r for r, o in enumerate(owner) if o == i]
                if rows_of and rows_of[0] < off: st["off"] = rows_of[0]
                elif rows_of and rows_of[-1] >= off + body:
                    st["off"] = min(rows_of[0], rows_of[-1] - body + 1)
            if k in ("q", "\x03"): break
            elif k in ("j", "\x1b[B"):
                if notes: st["sel"] = 0 if sel is None else min(sel + 1, len(notes) - 1); show(st["sel"])
            elif k in ("k", "\x1b[A"):
                if notes: st["sel"] = 0 if sel is None else max(sel - 1, 0); show(st["sel"])
            elif k == "WDN": st["off"] += 3
            elif k == "WUP": st["off"] -= 3
            elif k == " ": st["off"] += body
            elif k == "g": st["off"], st["sel"] = 0, (0 if notes else None)
            elif k == "G": st["off"] = maxoff
            elif k == "\x1b": st["sel"] = None
            elif folder and k in ("\r", "\n"):
                closed ^= {folder["folder"]}; st["mt"] = None
            elif ARCHIVE_VIEW:
                if k == "r" and e:
                    t = restore(PATH, e["raw"]); say(("back: " + t[:30]) if t else "not found")
                elif k == "D" and e:
                    say(("deleted: " + e["title"][:30]) if confirm("delete for good: " + e["title"], rows)
                        and forget(PATH, e["raw"]) else "kept")
            elif k == "f":
                ts = [None] + tabs_in(PATH)
                ONLY_TAB = ts[(ts.index(ONLY_TAB) + 1) % len(ts)] if ONLY_TAB in ts else None
                st.update(mt=None, sel=None, off=0)
                say("from " + ONLY_TAB if ONLY_TAB else ("every tab" if len(ts) > 1 else "no note says its tab yet"))
            elif k == "/":
                q = search_prompt(rows, st["q"])
                if q is not None:
                    st.update(q=q, sel=None, off=0)
            elif k in ("a", "t", "i"):                # into the project you're looking at
                at = ONLY_PROJECT or (folder["folder"] if folder else e["project"] if e else "")
                compose({"a": "note", "t": "todo", "i": "idea"}[k], project=at); say("")
            elif k == "u":
                t = restore(PATH); say(("back: " + t[:30]) if t else "nothing archived")
            elif e and k == "e": say(edit(e))
            elif e and k == "d":
                say("archived · u brings it back" if archive(PATH, e["raw"]) else "not found")
            elif e and k == "x" and e["kind"] == "todo":
                say("done · u brings it back" if archive(PATH, e["raw"], done=True) else "not found")
            elif e and k == "c": say(chat(e))
            elif e and k == "w": say(to_workspace(e))
            elif e and k == "m": say(move(e, rows))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n")
