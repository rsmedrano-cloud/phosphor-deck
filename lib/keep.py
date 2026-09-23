"""Turn a tab you arranged by hand into a tab in your profile.

zellij can describe the session it is running (`zellij action dump-layout`).
This reads that description back into the shape the profile uses, so you can
split panes, open what you want in each, and keep the result without writing
TOML: `phosphor keep` (or k in the DECK tab).

Only the panes are kept, never the tab bar (gen writes that itself), and a
pane started through `phosphor run` is read back as the command it watches.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

HOME = os.path.expanduser("~")

# ── the KDL that zellij dumps ─────────────────────────────────
def tokens(s):
    """Words and "quoted strings" of one line."""
    out, i = [], 0
    while i < len(s):
        if s[i].isspace():
            i += 1
        elif s[i] == '"':
            j = s.find('"', i + 1)
            if j < 0: j = len(s)
            out.append(("str", s[i + 1:j])); i = j + 1
        else:
            j = i
            while j < len(s) and not s[j].isspace(): j += 1
            out.append(("bare", s[i:j])); i = j
    return out

def parse(text):
    """A tree of {word, attrs, args, children}."""
    root = {"word": "layout", "attrs": {}, "args": [], "children": []}
    stack = [root]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line == "}":
            if len(stack) > 1: stack.pop()
            continue
        opens = line.endswith("{")
        body = line[:-1].strip() if opens else line
        toks = tokens(body)
        if not toks:
            continue
        node = {"word": toks[0][1], "attrs": {}, "args": [], "children": []}
        for kind, t in toks[1:]:
            if kind == "str":
                node["args"].append(t)
            elif "=" in t:
                k, v = t.split("=", 1)
                node["attrs"][k] = v.strip('"')
            else:
                node["args"].append(t)
        stack[-1]["children"].append(node)
        if opens:
            stack.append(node)
    return root

# ── back into profile shape ───────────────────────────────────
def run_args(pane):
    """The `phosphor run ...` arguments of a pane, or None."""
    cmd = pane["attrs"].get("command", "")
    args = []
    for c in pane["children"]:
        if c["word"] == "args":
            args = list(c["args"])
    if cmd.endswith("/phosphor") or os.path.basename(cmd) == "phosphor":
        return args
    if args and (args[0].endswith("/phosphor") or os.path.basename(args[0]) == "phosphor"):
        return args[1:]
    return None

def fold(args, ctx):
    """gen expands @hosts, @work, @mount_root before zellij sees them; put the
    tokens back, or a kept tab would freeze today's addresses into the profile."""
    for tok in ctx["tokens"]:
        if args == ctx["expand"](tok):
            return [tok]
    return [a.replace(ctx["root"], "@mount_root") for a in args]

def fold_ssh(target, ctx):
    """An ssh target as a role token (@work) when the role names one machine."""
    for tok in ctx["tokens"]:
        if tok != "@hosts" and ctx["expand"](tok) == [target]:
            return tok
    return target

def cells(size):
    """zellij dumps a fixed size as "18" and a share as "62%"."""
    if isinstance(size, str) and size.isdigit():
        return int(size)
    return size

def where(pane, ctx):
    """A pane's cwd, if it isn't the one the whole layout runs in. zellij
    dumps it relative to that one."""
    cwd = pane["attrs"].get("cwd")
    if not cwd:
        return None
    if not cwd.startswith("/"):
        cwd = os.path.join(ctx.get("cwd") or HOME, cwd)
    return None if cwd == HOME else cwd.replace(HOME, "~", 1)

def spec_of(pane, ctx):
    """One pane as the profile writes it, or None for a pane to skip."""
    if any(c["word"] == "plugin" for c in pane["children"]):
        return None                       # the tab bar: gen writes it
    kids = [c for c in pane["children"] if c["word"] == "pane"]
    spec = {}
    size = pane["attrs"].get("size")
    if kids:                              # a container: keep its shape
        inner = [s for s in (spec_of(k, ctx) for k in kids) if s is not None]
        if not inner:
            return None
        spec["split"] = "cols" if pane["attrs"].get("split_direction") == "vertical" else "rows"
        spec["panes"] = inner
        if size: spec["size"] = cells(size)
        return spec
    a = run_args(pane)
    if a is None:                         # a pane opened by hand: a shell
        cwd = where(pane, ctx)
        if cwd: spec["cwd"] = cwd
        if size: spec["size"] = cells(size)
        return spec
    flags, cmd = a[1:], []
    if "--" in flags:
        i = flags.index("--")
        cmd, flags = flags[i + 1:], flags[:i]
    if not cmd:
        return None
    exe = os.path.basename(cmd[0])
    if exe == "ssh":
        spec["ssh"] = fold_ssh(cmd[-1], ctx)
        spec["reconnect"] = "--reconnect" in flags
    elif cmd[0].endswith("/phosphor") or exe == "phosphor":
        spec["cmd"] = "phosphor " + " ".join(cmd[1:2])
        rest = fold(cmd[2:], ctx) if cmd[2:] else []
        if rest: spec["args"] = rest
    else:
        spec["cmd"] = exe
        rest = fold(cmd[1:], ctx) if cmd[1:] else []
        if rest: spec["args"] = rest
    if "--alt" in flags: spec["alt"] = True
    if "--wait" in flags: spec["needs_size"] = True
    cwd = where(pane, ctx)
    if cwd: spec["cwd"] = cwd
    if size: spec["size"] = cells(size)
    return spec

def context(prof=None, cwd=None):
    """What the profile would have expanded, so it can be folded back."""
    if prof is None:
        prof, _ = deckconf.load()
    import gen
    g = gen.Ctx(prof)
    return {"root": deckconf.mount_root(prof), "expand": g.expand, "cwd": cwd or HOME,
            "tokens": ["@mount_root", "@hosts"] +
                      ["@" + h["role"] for h in deckconf.hosts(prof)
                       if h.get("role") and not h.get("local")]}

def tab_specs(layout, name=None, ctx=None):
    """(tab name, [pane specs], split) for one tab of a dumped layout."""
    # the dump is wrapped in one `layout { ... }` node
    while not any(c["word"] == "tab" for c in layout["children"]):
        inner = [c for c in layout["children"] if c["children"]]
        if not inner:
            return None, [], None
        layout = inner[0]
    tabs = [t for t in layout["children"] if t["word"] == "tab"]
    if ctx is None:
        ctx = context(cwd=next((c["args"][0] for c in layout["children"]
                                if c["word"] == "cwd" and c["args"]), HOME))
    if name:
        tabs = [t for t in tabs if t["attrs"].get("name") == name]
    else:
        tabs = [t for t in tabs if t["attrs"].get("focus") == "true"] or tabs
    if not tabs:
        return None, [], None
    tab = tabs[0]
    panes = [c for c in tab["children"] if c["word"] == "pane"]
    specs = [s for s in (spec_of(p, ctx) for p in panes) if s is not None]
    # one container holding everything is the tab's own split, not a pane
    if len(specs) == 1 and "panes" in specs[0] and "size" not in specs[0]:
        return tab["attrs"].get("name"), specs[0]["panes"], specs[0]["split"]
    return tab["attrs"].get("name"), specs, None

# ── as TOML ───────────────────────────────────────────────────
def val(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, int): return str(v)          # a size in cells, not a string
    if isinstance(v, list): return "[" + ", ".join(val(x) for x in v) + "]"
    if isinstance(v, dict): return inline(v)
    return '"%s"' % str(v).replace('"', '\\"')

def inline(spec):
    return "{ " + ", ".join("%s = %s" % (k, val(v)) for k, v in spec.items()) + " }"

def block(name, specs, split=None):
    out = ["[[tabs]]", 'name  = "%s"' % name]
    if split:
        out.append('split = "%s"' % split)
    out.append("panes = [")
    for s in specs:
        out.append("  %s," % inline(s))
    out.append("]")
    return "\n".join(out) + "\n"

# ── into the profile ──────────────────────────────────────────
def put(text, name, blk):
    """Replace that tab's block, or add it at the end of the tabs."""
    lines = text.split("\n")
    out, i, done = [], 0, False
    while i < len(lines):
        if lines[i].strip() == "[[tabs]]":
            j = i + 1
            while j < len(lines) and lines[j].strip() != "[[tabs]]" and not lines[j].lstrip().startswith("["):
                j += 1
            body = "\n".join(lines[i:j])
            if re.search(r'^name\s*=\s*"%s"' % re.escape(name), body, re.M):
                out.append(blk.rstrip("\n"))
                out.append("")
                i = j; done = True; continue
            out.extend(lines[i:j]); i = j; continue
        out.append(lines[i]); i += 1
    if not done:
        out += ["", blk.rstrip("\n"), ""]
    return "\n".join(out)

def save(name, blk):
    """Write it, but only if the profile still parses afterwards."""
    p = deckconf.path()
    if deckconf.example():                 # never write into the repo's example
        print(row(BAD, "not saved", "there's no profile yet: phosphor init")); return False
    prof, _ = deckconf.load()
    already = any(t.get("name") == name and deckconf.is_real_tab(t) for t in (prof or {}).get("tabs", []))
    src = None if already else deckconf.tabs_d_names().get(name)
    if src:
        print(row(BAD, "not saved", "%s comes from %s: edit that file instead" %
                  (name, src.replace(os.path.expanduser("~"), "~", 1))))
        return False
    text = open(p).read()
    new = put(text, name, blk)
    try:
        prof = deckconf.tomllib.loads(new)
    except Exception as e:
        print(row(BAD, "not saved", str(e)[:60])); return False
    if not any(t.get("name") == name for t in prof.get("tabs", [])):
        print(row(BAD, "not saved", "the tab isn't in the result")); return False
    open(p + ".bak", "w").write(text)
    open(p, "w").write(new)
    print(row(OK, "saved", p, note="backup: deck.toml.bak"))
    return True

def dump():
    z = os.path.join(HOME, ".local/bin/zellij")
    if not os.path.exists(z):
        import shutil
        z = shutil.which("zellij") or "zellij"
    import subprocess
    r = subprocess.run([z, "action", "dump-layout"], capture_output=True, text=True, timeout=20)
    return r.stdout if r.returncode == 0 else ""

def main():
    from init import ask, pick, yes
    argv = sys.argv[1:]
    dry = "--dry-run" in argv or "-n" in argv
    names = [a for a in argv if not a.startswith("-")]
    text = dump()
    if not text.strip():
        print("  zellij didn't describe the session: run this from inside the deck")
        return 1
    layout = parse(text)
    want = names[0] if names else None
    if not want and "--pick" in argv:
        tabs = [t["attrs"].get("name", "?") for t in layout["children"][0]["children"]
                if t["word"] == "tab"] if layout["children"] else []
        tabs = tabs or [t["attrs"].get("name", "?") for t in layout["children"] if t["word"] == "tab"]
        if not tabs:
            print("  no tabs to keep"); return 1
        want = tabs[pick("which tab do you want to keep?", tabs, 0)]
    name, specs, split = tab_specs(layout, want)
    if not specs:
        print("  nothing to keep in that tab"); return 1
    if not name or name.startswith("Tab #"):
        name = ask("a name for this tab", name or "TAB").upper()
    blk = block(name, specs, split)
    print()
    print(BLOOM + "  %s, as it is now" % name + RST)
    for l in blk.splitlines():
        print("  " + FG + l + RST)
    print()
    if dry:
        return 0
    if not yes("keep it in your profile?", True):
        return 0
    if not save(name, blk):
        return 1
    import subprocess
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  " + DIM + "kept. It comes back like this after phosphor restart." + RST)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
