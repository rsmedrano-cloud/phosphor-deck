"""phosphor init - builds the profile, detecting a lot and asking little."""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import mesh, deckconf

HOME = os.path.expanduser("~")
OUT  = os.path.join(HOME, ".config/phosphor/deck.toml")
COLLECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "share", "collect.sh")

def sh(cmd, t=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return 1, ""

def ask(q, default=""):
    hint = DIM + " [" + (default or "-") + "]" + RST if default else ""
    try:
        v = input("  " + BLOOM + "? " + RST + q + hint + " ").strip()
    except (EOFError, KeyboardInterrupt):
        print(); raise SystemExit(1)
    return v or default

def _key():
    return getkey() or ""

def pick(q, options, default=0):
    """Arrows, j/k, a number or Enter. Without a terminal (a pipe, a
    test) it falls back to typing the number."""
    print("  " + BLOOM + "? " + RST + q)
    if not sys.stdin.isatty():
        for i, o in enumerate(options):
            print("     %s %s%d%s %s" % (PH + "›" + RST if i == default else " ", AMB, i + 1, RST, o))
        while True:
            v = ask("number", str(default + 1))
            try:
                n = int(v) - 1
                if 0 <= n < len(options): return n
            except ValueError:
                pass
    sel, n = default, len(options)
    def draw(first):
        if not first: sys.stdout.write("\x1b[%dA" % (n + 1))
        for i, o in enumerate(options):
            if i == sel:
                sys.stdout.write("\r\x1b[K     " + PH + "› " + AMB + str(i + 1) + RST + " " + BLOOM + o + RST + "\n")
            else:
                sys.stdout.write("\r\x1b[K       " + DIM + str(i + 1) + " " + RST + o + "\n")
        sys.stdout.write("\r\x1b[K  " + DIM + "↑↓ or a number, Enter to choose" + RST + "\n")
        sys.stdout.flush()
    draw(True)
    while True:
        k = _key()
        if isinstance(k, tuple): continue
        if k in ("\x1b[A", "k"): sel = (sel - 1) % n
        elif k in ("\x1b[B", "j"): sel = (sel + 1) % n
        elif isinstance(k, str) and k.isdigit() and 0 < int(k) <= n: sel = int(k) - 1; draw(False); return sel
        elif k in ("\r", "\n"): return sel
        elif k in ("\x03", "\x04"): print(); raise SystemExit(1)
        else: continue
        draw(False)

def yes(q, default=True):
    d = "Y/n" if default else "y/N"
    v = ask(q + DIM + " (" + d + ")" + RST, "").lower()
    if not v: return default
    return v.startswith("y") or v.startswith("s")   # "s" also: sí

def discover(use_tailscale=True):
    """Candidates: tailscale peers (tailscale.com or headscale, same client)
    plus ~/.ssh/config aliases."""
    cands, me = {}, None
    rc, out = sh("tailscale status 2>/dev/null") if use_tailscale else (1, "")
    if rc == 0:
        rc2, myip = sh("tailscale ip -4 2>/dev/null")
        myip = (myip or "").split("\n")[0].strip()
        for line in out.splitlines():
            p = line.split()
            if len(p) < 2 or not re.match(r"^\d+\.", p[0]): continue
            ip, name = p[0], p[1]
            osname = p[3] if len(p) > 3 else "?"
            offline = "offline" in line
            if ip == myip: me = name
            cands[name] = {"ip": ip, "offline": offline, "os": osname,
                           "src": "tailscale"}
    # phones and tablets are viewers, not fleet nodes: never mounted
    for n in list(cands):
        if cands[n].get("os") in ("android", "iOS"):
            cands[n]["viewer_only"] = True
    for name in ssh_hosts():
        if name not in cands:
            cands[name] = {"ip": None, "offline": False, "src": "~/.ssh/config"}
    return cands, me

# Code forges and git-only servers live in ~/.ssh/config too, but they are
# not machines to watch: offering "github.com" as a fleet host reads as if
# the deck wanted your credentials.
FORGES = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht", "gitea.com")

def ssh_hosts():
    """Plain Host aliases from ~/.ssh/config that look like machines."""
    cfg = os.path.join(HOME, ".ssh/config")
    if not os.path.exists(cfg):
        return []
    blocks, cur = [], None
    for line in open(cfg):
        m = re.match(r"^\s*(\w+)\s+(.*?)\s*$", line)
        if not m: continue
        k, v = m.group(1).lower(), m.group(2)
        if k == "host":
            cur = {"names": v.split(), "hostname": "", "user": ""}; blocks.append(cur)
        elif cur is not None and k in ("hostname", "user"):
            cur[k] = v
    out = []
    for b in blocks:
        if b["user"].lower() == "git": continue
        for n in b["names"]:
            if any(c in n for c in "*?!"): continue
            where = (b["hostname"] or n).lower()
            if any(where == f or where.endswith("." + f) for f in FORGES): continue
            if "git" in n.lower() and not b["hostname"]: continue
            out.append(n)
    return out

def try_ssh(target):
    rc, out = sh("ssh -o BatchMode=yes -o ConnectTimeout=6 %s 'echo __ok__' 2>&1" % target, t=12)
    return ("__ok__" in out), out

def why_not(out):
    """A short reason why a candidate didn't give us a shell."""
    o = out.lower()
    if "shell access" in o or "pty allocation" in o or "interactive" in o:
        return "no shell (a git server?)"
    if "denied" in o or "publickey" in o:
        return "doesn't take your key"
    if "host key verification" in o:
        return "unknown host key"
    return "no answer"

def reachable(names):
    """Try ssh on every candidate at once: only machines that really run a
    shell command are worth offering. Code forges answer ssh too, but never
    with a shell, so they drop out here whatever their name."""
    from concurrent.futures import ThreadPoolExecutor
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(names, ex.map(try_ssh, names)))

def probe(alias):
    """Does it answer, and which disks does it have?

    A permission failure usually means the user is different over there (a
    work laptop vs a server), so ask instead of silently skipping the host."""
    ok, out = try_ssh(alias)
    target = alias
    if not ok and ("denied" in out.lower() or "publickey" in out.lower()):
        print(row(AMB, alias, "rejects '%s'" % (os.environ.get("USER") or "?"),
                  note="different user?"))
        u = ask("user on %s (empty = skip it)" % alias, "")
        if not u: return None
        target = "%s@%s" % (u, alias)
        ok, out = try_ssh(target)
        if not ok:
            print(row(BAD, alias, out.strip().splitlines()[-1][:40] if out.strip() else "no answer"))
            return None
    if not ok: return None
    alias = target
    info = {"user": None, "mounts": [], "target": alias}
    rc, who = sh("ssh -o BatchMode=yes %s 'whoami' 2>/dev/null" % alias, t=10)
    info["user"] = who.strip() or None
    if os.path.exists(COLLECT):
        rc, out = sh("ssh -o BatchMode=yes %s 'sh -s' < %s 2>/dev/null" % (alias, COLLECT), t=30)
        for l in out.splitlines():
            if l.startswith("MNT="):
                t, p, s = l[4:].split("|")
                info["mounts"].append((t, s))
    return info

ROLES = ["brain   (holds the session, must always be on)",
         "work    (your projects live here)",
         "desktop (a desk machine)",
         "storage (disks only)",
         "viewer  (only looks, never mounted)"]
RKEY = ["brain", "work", "desktop", "storage", "viewer"]

def run():
    print()
    print(BLOOM + "  PHOSPHOR DECK · init" + RST)
    print()
    print("  " + FG + "Three ideas, then a few questions:" + RST)
    print("   " + AMB + "the deck " + RST + "  your terminal session with its tabs; it keeps running when you leave")
    print("   " + AMB + "the brain" + RST + "  the machine that keeps it running; you get into it from anywhere")
    print("              " + DIM + "(this one, if it stays on)" + RST)
    print("   " + AMB + "~/fleet  " + RST + "  your machines' files as folders, to browse in the CLOUD tab;")
    print("              " + DIM + "nothing is copied or moved, you see them where they are" + RST)
    print("  " + DIM + "No root. Everything goes into your home folder." + RST)

    print("\n" + rule("network"))
    kind, control = mesh.detect()
    if kind == "headscale":
        print(row(OK, "detected", "headscale", note=control))
    nets = ["tailscale  (tailscale.com)", "headscale  (your own control server)",
            "none       (plain ssh: ~/.ssh/config, LAN — or just this machine)"]
    net = mesh.KINDS[pick("how do your machines reach each other? (only matters if you have more than one)",
                          nets, mesh.KINDS.index(kind))]

    print("\n" + rule("discovering"))
    cands, me = discover(net != "none")
    if not cands:
        print(row(AMB, "no candidates", "neither tailscale nor ~/.ssh/config"))
    hosts = []

    local_name = me or os.uname().nodename
    print(row(OK, "this machine", local_name, note="local"))
    viewers = [n for n, c in cands.items() if c.get("viewer_only")]
    for n, c in sorted(cands.items()):
        if n == me or c.get("viewer_only"): continue
        tag = "offline" if c["offline"] else c.get("os", "")
        print(row(DIM + "·" + RST, n, c["ip"] or c["src"], note=tag))
    if viewers:
        print(row(DIM + "·" + RST, "%d viewers" % len(viewers),
                  ", ".join(sorted(viewers))[:44], note="never mounted"))

    print("\n" + rule("this machine"))
    if yes("is this the brain? (it stays on and keeps the deck running)", True):
        mounts = ["/", "~"]
        print("    " + DIM + "~/fleet/%s/root and ~/fleet/%s/home will show / and your home" % (local_name, local_name) + RST)
        rc, out = sh("df -h --output=target -x tmpfs -x devtmpfs -x overlay 2>/dev/null | tail -n +2")
        extra = [m.strip() for m in out.splitlines()
                 if m.strip().startswith("/mnt") or m.strip().startswith("/media")]
        if extra and yes("also show these disks in ~/fleet (nothing is copied): %s" % ", ".join(extra), True):
            mounts += extra
        h = {"name": local_name, "role": "brain", "local": True, "mounts": mounts}
        if me and cands.get(me, {}).get("ip"): h["ip"] = cands[me]["ip"]
        hosts.append(h)
    else:
        h = {"name": local_name, "role": "viewer", "local": True}
        if me and cands.get(me, {}).get("ip"): h["ip"] = cands[me]["ip"]
        hosts.append(h)

    print("\n" + rule("the fleet"))
    todo = [n for n, c in sorted(cands.items())
            if n != me and not c.get("viewer_only") and not c["offline"]]
    if todo:
        print("    " + DIM + "trying ssh on %d candidates at once..." % len(todo) + RST)
    res = reachable(todo)
    for n in todo:
        if not res[n][0]:
            print(row(DIM + "·" + RST, n, why_not(res[n][1]), note="skipped"))
    off = [n for n, c in sorted(cands.items()) if c["offline"] and not c.get("viewer_only")]
    if off:
        print(row(DIM + "·" + RST, "%d offline" % len(off), ", ".join(off)[:44], note="skipped"))
    ok = [n for n in todo if res[n][0]]
    if not ok:
        print("    " + DIM + "no other machine answered: the deck starts with this one" + RST)
        print("    " + DIM + "(add more later with phosphor setup)" + RST)
    declined = set()
    for n in ok:
        c = cands[n]
        # tailscale peers are yours; ~/.ssh/config hosts are often someone
        # else's servers (work, production): those need a yes, not an Enter
        if not yes("watch %s as a machine of your fleet? (ssh in to read CPU, RAM, disks)" % n,
                   bool(c.get("ip"))):
            declined.add(n)
            continue
        info = probe(n)
        if info is None:
            print(row(BAD, n, "no ssh answer", note="skipping it"))
            continue
        r = RKEY[pick("role of %s" % n, ROLES, 1)]
        h = {"name": n, "role": r, "ssh": n}
        if "@" in info.get("target", ""):
            h["user"] = info["target"].split("@")[0]
        if c["ip"]: h["ip"] = c["ip"]
        if info["user"] and info["user"] != os.environ.get("USER"):
            h["user"] = info["user"]
        if r != "viewer":
            opts = [m[0] + "  " + m[1] for m in info["mounts"]] or ["/"]
            opts.append("don't mount")
            k = pick("what to mount from %s" % n, opts, 0)
            if k < len(opts) - 1:
                h["mount"] = info["mounts"][k][0] if info["mounts"] else "/"
        hosts.append(h)

    tun = []
    if hosts and hosts[0].get("role") == "brain":
        import tunnels
        fw = {a: f for a, f in tunnels.ssh_config_forwards().items() if a not in declined}
        if fw:
            print("\n" + rule("tunnels"))
            print("    " + DIM + "these ~/.ssh/config hosts have LocalForward tunnels; the deck can keep them up" + RST)
            tunnels.warn()
            for alias in sorted(fw):
                what = ", ".join("%s→%s%s" % (l, t, " " + lab if lab else "") for l, t, lab in fw[alias])
                if yes("keep %s's tunnels up? (%s)" % (alias, what[:70]), False):
                    tun.append(alias)

    print("\n" + rule("taste"))
    shapes = ["homelab   fleet panel, file browser, monitoring -- the default",
              "revived   one lean machine: a shell, monitoring, notes -- no CLOUD tab",
              "dev       a two-assistant tab up front, the rest stays"]
    shape = SHAPES[pick("which shape fits how you'll use it? (phosphor recipe adds more later)", shapes, 0)]
    themes = ["p31    green phosphor (VT100)", "p3     amber (IBM 5151)",
              "p4     white", "paper  paper (e-ink)"]
    theme = ["p31", "p3", "p4", "paper"][pick("color", themes, 0)]
    editor_pick, shell_pick = tools()
    comms_opts = ["matterhorn (Mattermost)", "iamb (Matrix)", "gomuks (Matrix)", "none"]
    ci = pick("chat app for a COMMS tab (none if you don't use one of these)", comms_opts, 3)
    comms = ["matterhorn", "iamb", "gomuks", None][ci]
    import notes as notesmod
    notes_folder = notesmod.choose_folder(None)

    web = False
    brain = bool(hosts) and hosts[0].get("role") == "brain"
    if brain and net == "tailscale":
        import web as webmod
        ok_web, _ = webmod.usable({"deck": {"mesh": net}})
        if ok_web:
            web = yes("also open the deck from a browser? only your tailscale devices can reach it,"
                      " with a login token", False)

    print("\n" + rule("summary"))
    print(row(OK, "shape", shape))
    for h in hosts:
        print(row(OK, h["name"], h["role"],
                  note=h.get("mount") or ("local" if h.get("local") else "")))
    print(row(OK, "network", net))
    if web: print(row(OK, "browser", "on, inside your tailnet"))
    print(row(OK, "color", theme))
    print(row(OK, "editor", editor_pick))
    print(row(OK, "shell", shell_pick))
    print(row(OK, "chat", comms or "none"))
    print(row(OK, "notebook", notes_folder.replace(HOME, "~", 1) if notes_folder else "private"))
    if not yes("\n  write the profile?", True):
        print("  " + DIM + "cancelled, nothing written" + RST); return 1

    old_notes = notesmod.PATH
    body = render(hosts, theme, comms, net, web, tun, editor_pick, shell_pick, notes_folder, shape)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        import deckconf
        deckconf.backup(OUT, open(OUT).read())
        print(row(AMB, "backup", OUT + ".bak"))
    open(OUT, "w").write(body)
    print(row(OK, "profile", OUT))
    if notes_folder:
        moved = notesmod.migrate(old_notes, os.path.join(notes_folder, "notes.md"))
        if moved: print(row(OK, "notebook moved", ", ".join(moved)))
    me_ = os.path.join(REPO, "phosphor")
    if brain and sys.stdin.isatty() and yes("\n  build the deck and start it now?", True):
        subprocess.run([sys.executable, me_, "gen"])
        subprocess.run([sys.executable, me_, "up"])
        if web:
            import web as webmod
            webmod.on(restart=False)          # the session was just created shareable
        if yes("  will you also get in from a phone or tablet?", False):
            import deckconf, phone
            phone.instructions(deckconf.load()[0])
        if not os.environ.get("ZELLIJ") and \
                yes("  get in now? (leave any time with Alt-x or Ctrl-q)", True):
            os.execv(sys.executable, [sys.executable, me_, "attach"])
        if not os.environ.get("ZELLIJ"):
            print("  " + PH + "get in any time: deck" + RST)
        return 0
    print()
    if brain:
        print("  " + PH + "next: phosphor gen && phosphor up && deck" + RST)
    else:
        print("  " + PH + "next: phosphor gen" + RST + DIM + "   writes the `deck` command that gets you in" + RST)
    print()
    return 0

def host_block(h):
    """One [[hosts]] block as lines. setup uses it too."""
    L = ["[[hosts]]", 'name  = "%s"' % h["name"], 'role  = "%s"' % h["role"]]
    if h.get("local"): L.append("local = true")
    for k in ("ip", "ssh", "user", "mount"):
        if h.get(k): L.append('%-5s = "%s"' % (k, h[k]))
    if h.get("mounts"):
        L.append("mounts = [%s]" % ", ".join('"%s"' % m for m in h["mounts"]))
    return L

def pick_one(question, names, current, note):
    """Pick among what's installed; the current one first."""
    have = deckconf.installed(names)
    cur = os.path.basename(current.split()[0]) if current else ""
    if cur and cur not in have: have.insert(0, cur)
    if not have: return current
    i = pick(question + DIM + "  " + note + RST, have, have.index(cur) if cur in have else 0)
    return have[i]

def tools():
    """The editor files open with and the shell every shell pane runs."""
    ed = pick_one("editor for files", deckconf.EDITORS, deckconf.editor(None),
                  "(more in phosphor store: micro, helix)")
    shell = pick_one("shell for new panes", deckconf.SHELLS, deckconf.login_shell() or "bash",
                  "(yours by default)")
    return ed, shell

SHAPES = ["homelab", "revived", "dev"]

def render(hosts, theme, comms, net="auto", web=False, tun=(), editor=None, shell=None,
           notes_folder=None, shape="homelab"):
    L = ["# Written by `phosphor init`. Edit it freely.",
         "# The deck's source of truth: change it and run `phosphor gen`.", "",
         "[deck]", 'session = "deck"', 'theme   = "%s"' % theme,
         'mesh    = "%s"' % net, 'mount_root = "~/fleet"'] + (['web     = true'] if web else []) \
        + (['editor  = "%s"' % editor] if editor else []) + (['shell   = "%s"' % shell] if shell else []) + [""]
    if notes_folder:
        L += ["[notes]", 'folder = "%s"' % notes_folder, ""]
    for h in hosts:
        L += host_block(h) + [""]
    L.append("# Tabs, in order: Alt-1..9 or tap the bar. Shape: %s (phosphor recipe changes it)." % shape)
    if comms:
        L += ["[[tabs]]", 'name  = "COMMS"', 'panes = [ { cmd = "%s" } ]' % comms, ""]
    if shape == "dev":
        L += ["[[tabs]]", 'name  = "DEV"', 'split = "cols"', "panes = [",
              '  { cmd = "claude" },', '  { cmd = "codex" },', "]", ""]
    if any(h["role"] == "work" for h in hosts):
        L += ["[[tabs]]", 'name  = "WORK"',
              'panes = [ { ssh = "@work", reconnect = true } ]', ""]
    if shape == "revived":
        L += ["[[tabs]]", 'name  = "SYS"', 'split = "rows"', "panes = [",
              '  { cmd = "phosphor pulse", size = 9 },',
              '  { cmd = "phosphor fleet", size = "78%" },',
              '  { cmd = "phosphor services" },', "]", ""]
    else:
        L += ["[[tabs]]", 'name  = "SYS"', 'split = "rows"', "panes = [",
              '  { cmd = "phosphor pulse", size = 9 },',
              '  { cmd = "phosphor fleet", size = "50%" },',
              '  { cmd = "gping", alt = true, args = ["@hosts"], size = "25%" },',
              '  { cmd = "phosphor services" },', "]", ""]
    if shape != "revived":
        L += ["[[tabs]]", 'name  = "CLOUD"', 'split = "cols"', "panes = [",
              '  { cmd = "yazi", args = ["@mount_root"], size = "64%", needs_size = true },',
              '  { split = "rows", panes = [',
              '      { cmd = "btop", args = ["-p", "1"], size = "55%" },',
              '      { cmd = "ctop", alt = true, args = ["-s", "cpu"], size = "45%", needs_size = true },',
              "  ]},", "]", ""]
    L += ["[[tabs]]", 'name  = "DECK"', 'split = "cols"', "panes = [",
          '  { cmd = "phosphor panel", size = "50%" },',
          '  { cmd = "phosphor keys" },', "]", ""]
    L += ["[[tabs]]", 'name  = "NOTES"', 'panes = [ { cmd = "phosphor notes" } ]', ""]
    for t in tun:
        L += ["[[tunnels]]", 'host = "%s"' % t, ""]
    return "\n".join(L)
