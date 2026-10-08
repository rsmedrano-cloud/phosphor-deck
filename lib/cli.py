"""cli - every phosphor command, from one definition.

share/commands.json describes each command once: its category, usage,
summary, the flags and words it takes, its aliases, the module that runs
it, and whether it mutates anything. Everything that lists commands reads
it from here: `phosphor help`, `phosphor CMD --help`, the dispatcher, the
`phosphor commands` menu and tab completion. A new command is one entry
there, not six edits that drift apart.
"""
import json, os, re, sys, textwrap
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import REPO

MANIFEST = os.path.join(REPO, "share", "commands.json")
_cache = None


def manifest():
    """The whole file, _schema and _categories included; {} if unreadable."""
    global _cache
    if _cache is None:
        try:
            with open(MANIFEST) as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def entries(hidden=False):
    """{name: entry} in the file's order (category order), hidden ones only on request."""
    return {k: v for k, v in manifest().items()
            if not k.startswith("_") and (hidden or not v.get("hidden"))}


def categories():
    """[(category, [(name, entry), ...]), ...] in order, without hidden commands."""
    cmds = entries()
    return [(cat, [(n, e) for n, e in cmds.items() if e.get("category") == cat])
            for cat in manifest().get("_categories", [])]


def resolve(cmd):
    """The command an alias stands for (`deck` -> `attach`); the name itself otherwise."""
    for name, e in entries(hidden=True).items():
        if cmd in e.get("aliases", ()):
            return name
    return cmd


def get(cmd):
    return entries(hidden=True).get(resolve(cmd))


def module(cmd):
    """The lib/ module that runs cmd, or None: unknown, or run by the dispatcher itself."""
    e = get(cmd)
    if not e:
        return None
    mod = e.get("module", resolve(cmd))
    if mod and os.path.exists(os.path.join(REPO, "lib", mod + ".py")):
        return mod
    return None


def topics():
    """The manual's pages, so a new one completes without touching anything."""
    return sorted(f[:-3] for f in os.listdir(os.path.join(REPO, "doc/manual"))
                  if f.endswith(".md") and f != "README.md")


def words(e):
    return [w for x in e.get("words", []) for w in (topics() if x == "@topics" else [x])]


def usage_text(width=80):
    """`phosphor help`: every command by category, one line each."""
    out = ["phosphor - Phosphor Deck", ""]
    for cat, cmds in categories():
        out.append("  " + cat.lower())
        for name, e in cmds:
            head = "    phosphor " + name
            pad = 24
            if len(head) >= pad - 1:
                out.append(head)
                head = ""
            out += textwrap.wrap(e["summary"], width=width, initial_indent=head.ljust(pad),
                                 subsequent_indent=" " * pad)
        out.append("")
    out += ["  phosphor CMD --help   one command's usage and what it does",
            "  --json on fleet, services, containers, screens, mem, security, tunnel,",
            "         version, workspace list, panels, glance: the same data, for scripts"]
    out += textwrap.wrap("the manual:  phosphor help " + " | ".join(topics()), width=width,
                         initial_indent="  ", subsequent_indent=" " * 29)
    return "\n".join(out)


def help_for(cmd):
    """`phosphor CMD --help`: its usage, what it does and its flags, from the
    same entry the menu shows. False for a command it doesn't know."""
    e = get(cmd)
    if not e:
        return False
    print("usage: " + e["usage"])
    print("  " + e["summary"])
    if e.get("aliases"):
        print("  also: " + ", ".join("phosphor " + a for a in e["aliases"]))
    if e.get("options"):
        print("  options: " + " ".join(e["options"]))
    if e.get("note"):
        print()
        print(textwrap.fill(e["note"], width=78, initial_indent="  ", subsequent_indent="  "))
    print()
    print("  the manual: phosphor help commands")
    return True


def completions():
    """{name: (words, flags)} for every command and alias completion offers,
    and {flag: [values]} for the flags that take fixed ones."""
    after, values = {}, {}
    for name, e in entries().items():
        for n in [name] + e.get("aliases", []):
            after[n] = (words(e), e.get("options", []))
        values.update(e.get("values", {}))
    return after, values


FLAG = re.compile(r"^--?[A-Za-z][\w-]*(=.*)?$")


def check(cmd, argv):
    """The first flag in argv that cmd doesn't take, or None.

    Its entry's options and internal flags are the ones it takes; takes_value
    names those whose next word is their value, not a flag or a word.
    Nothing after a `--` is looked at: it belongs to the command being
    passed along. A free_text command (a note, a question) only has its
    leading flags looked at: once its text starts, `ls -la` in it is text.
    A word that isn't flag-shaped (`-`, `-5`, `a -b`) is never one. A hidden
    command, or one it doesn't know, is never refused here."""
    e = get(cmd)
    if not e or e.get("hidden"):
        return None
    known = set(e.get("options", [])) | set(e.get("internal", [])) | {"-h", "--help"}
    valued = set(e.get("takes_value", []))
    it = iter(argv)
    for a in it:
        if a == "--":
            return None
        if not FLAG.match(a):
            if e.get("free_text"):
                return None
            continue
        name = a.split("=", 1)[0]
        if name not in known:
            return a
        if name in valued and "=" not in a:
            next(it, None)
    return None
