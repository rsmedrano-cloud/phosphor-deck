"""phosphor gen - from the declarative profile to the real files.

Writes the session layout, per-tab layouts, the zellij theme, the systemd
units, the rclone remotes and the brain's disk links. fleet and path read
the profile themselves (through deckconf), so there's one source of truth.
"""
import hashlib, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

HOME = os.path.expanduser("~")
BIN  = os.path.join(HOME, ".local/bin")
ZDIR = os.path.join(HOME, ".config/zellij/layouts")
UDIR = os.path.join(HOME, ".config/systemd/user")
PHOSPHOR = os.path.join(REPO, "phosphor")       # wherever the repo lives

FUSERMOUNT = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"

def resolve(exe):
    """Absolute path: the zellij server doesn't inherit ~/.local/bin in PATH."""
    exe = os.path.expanduser(exe)
    if os.sep in exe: return exe
    p = os.path.join(BIN, exe)
    if os.path.isfile(p): return p
    return shutil.which(exe) or exe

class Ctx:
    def __init__(self, prof):
        self.prof   = prof
        self.hosts  = prof.get("hosts", [])
        self.deck   = prof.get("deck", {})
        self.root   = os.path.expanduser(self.deck.get("mount_root", "~/fleet"))
        self.byrole = {}
        for h in self.hosts:
            self.byrole.setdefault(h.get("role", "viewer"), []).append(h)
    def role(self, r):
        v = self.byrole.get(r)
        return v[0] if v else None
    def sorted_hosts(self):
        return deckconf.hosts(self.prof)
    def local(self):
        return next((h for h in self.hosts if h.get("local")), None)

    def is_brain(self):
        """There is ONE brain. A viewer never hosts a session of its own: it
        connects to the brain's. Giving it units would build a second brain."""
        h = self.local()
        return h is not None and h.get("role") == "brain"

    def brain(self):
        return next((h for h in self.hosts if h.get("role") == "brain"), None)

    def remotes(self):
        return [h for h in self.sorted_hosts()
                if not h.get("local") and h.get("mount")]
    def expand(self, tok):
        if tok == "@mount_root": return [self.root]
        if tok == "@hosts":
            return [h.get("ip") or h.get("ssh") or h["name"] for h in self.sorted_hosts()]
        if tok.startswith("@"):
            h = self.role(tok[1:])
            return [h.get("ssh") or h["name"]] if h else []
        return [tok]

def pane_kdl(spec, ctx, ind):
    """One pane (or a container of panes) as KDL."""
    pad = " " * ind
    size = spec.get("size")
    sz = (' size="%s"' % size) if isinstance(size, str) else (" size=%d" % size if size else "")

    if "panes" in spec:
        d = "vertical" if spec.get("split", "rows") == "cols" else "horizontal"
        out = ['%spane%s split_direction="%s" {' % (pad, sz, d)]
        for c in spec["panes"]:
            out.append(pane_kdl(c, ctx, ind + 4))
        out.append(pad + "}")
        return "\n".join(out)

    extra = ['%s    cwd "%s"' % (pad, os.path.expanduser(spec["cwd"]))] if spec.get("cwd") else []

    if "ssh" in spec:
        tgt = ctx.expand(spec["ssh"])
        tgt = tgt[0] if tgt else "localhost"
        return run_pane(pad, sz, ["ssh", "-t", tgt], extra, name=tgt.split("@")[-1].upper(),
                        reconnect=spec.get("reconnect", True))

    cmd = spec.get("cmd", "")
    if not cmd:
        return run_pane(pad, sz, [deckconf.shell(ctx.prof), "-l"], extra, name="SHELL")
    parts = cmd.split()
    exe, sub = parts[0], parts[1:]
    path = PHOSPHOR if exe == "phosphor" else resolve(exe)
    args = list(sub)
    for a in spec.get("args", []):
        args.extend(ctx.expand(a))
    # fonts without Braille draw gping's graph as boxes with hex numbers
    if os.path.basename(exe) == "gping" and ctx.deck.get("graphs") == "blocks" and "-s" not in args:
        args.append("-s")
    # gping and ctop take their color on the command line, not a config file
    if os.path.basename(exe) == "gping" and "-c" not in args and "--color" not in args:
        args += ["--color", hexc(PALETTES[theme_name(ctx.prof)]["ph"])]
    if os.path.basename(exe) == "ctop" and "-i" not in args:
        args += ctop_extra_args(theme_name(ctx.prof))
    return run_pane(pad, sz, [path] + args, extra,
                    name=(sub[0] if exe == "phosphor" and sub else os.path.basename(exe)).upper(),
                    wait=spec.get("needs_size"), alt=spec.get("alt"))

def kdl_str(x):
    return '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'

def run_pane(pad, sz, argv, extra, name=None, reconnect=False, wait=False, alt=False):
    """A pane whose program runs through `phosphor run`: when it ends, the
    pane asks (Enter opens it again, x closes the tab) instead of vanishing.

    Without an explicit `name`, zellij's own title falls back to the pane's
    command line -- which is phosphor's own install path, twice (`phosphor
    run` and the program it wraps). That's not just noise: it's your home
    directory and username, framed and left on screen for anyone who's
    ever screenshotted a tab. `name` is the label already picked for
    `phosphor run --name` (PULSE, FLEET, SHELL...); giving it to the pane
    itself as its zellij title costs nothing and means one is never shown
    without the other."""
    opts = (["--name", name] if name else []) + (["--reconnect"] if reconnect else []) \
        + (["--wait", "1"] if wait else []) + (["--alt"] if alt else [])
    body = ["%s    close_on_exit true" % pad,
            "%s    args %s" % (pad, " ".join(kdl_str(x) for x in ["run"] + opts + ["--"] + argv))] + extra
    nm = (' name=%s' % kdl_str(name)) if name else ""
    return '%spane%s%s command="%s" {\n%s\n%s}' % (pad, sz, nm, PHOSPHOR, "\n".join(body), pad)

def floating_notifier(ctx, ind):
    """One floating adjutant per tab, only with `notifier = true`.

    It starts hidden and `phosphor notify` shows it on the tab you're
    looking at; a click on it takes you to the event's tab."""
    pad = " " * ind
    face = ctx.deck.get("face", "")
    args = ['"adjutant"', '"--floating"']
    if face: args += ['"--face"', '"%s"' % face, '"--speed"', '"3"']
    return "\n".join([
        pad + "floating_panes {",
        pad + '    pane command="%s" {' % PHOSPHOR,
        pad + "        args " + " ".join(args),
        pad + "        width 34",
        pad + "        height 19",
        pad + '        x "62%"',
        pad + '        y "10%"',
        pad + "    }",
        pad + "}"])

def tab_body(tab, ctx, ind):
    panes = tab.get("panes", [{}])
    if len(panes) == 1 and "panes" not in panes[0]:
        return pane_kdl(panes[0], ctx, ind)
    d = "vertical" if tab.get("split", "rows") == "cols" else "horizontal"
    pad = " " * ind
    out = ['%spane split_direction="%s" {' % (pad, d)]
    for p in panes: out.append(pane_kdl(p, ctx, ind + 4))
    out.append(pad + "}")
    return "\n".join(out)

HEADER = """// GENERATED BY `phosphor gen` — don't edit by hand.
// Source of truth: %s
"""

def bars(ctx):
    """tabs (default): tab-bar, one line, with its "+" button (it opens the
    new-tab menu). compact: compact-bar, one line with the mode but no "+".
    full: tab-bar plus the status-bar with key hints (3 lines)."""
    b = ctx.deck.get("bar", "tabs")
    tab = 'pane size=1 borderless=true { plugin location="zellij:tab-bar"; }'
    if b == "compact":
        return ('pane size=1 borderless=true { plugin location="zellij:compact-bar"; }', None)
    if b == "full":
        return (tab, 'pane size=2 borderless=true { plugin location="zellij:status-bar"; }')
    return (tab, None)

def deck_kdl(prof, ctx, src):
    top, bottom = bars(ctx)
    out = [HEADER % src, "layout {", "    default_tab_template {", "        " + top,
           "        children"] + (["        " + bottom] if bottom else []) + ["    }", ""]
    # "+" and any new tab open the menu (phosphor new). It execs what you
    # pick, so when that exits the tab closes with it.
    out += ["    new_tab_template {", "        " + top,
            '        pane command="%s" {' % PHOSPHOR,
            "            close_on_exit true", '            args "new"', "        }"] \
        + (["        " + bottom] if bottom else []) + ["    }", ""]
    notifier = ctx.deck.get("notifier", False)      # off by default: see DECK_UP
    for i, tab in enumerate(deckconf.effective_tabs(prof)):
        foc = " focus=true" if i == 0 else ""
        out.append('    tab name="%s"%s {' % (tab["name"], foc))
        out.append(tab_body(tab, ctx, 8))
        if notifier:
            out.append(floating_notifier(ctx, 8))
        out.append("    }")
        out.append("")
    out.append("}")
    return "\n".join(out)

def tab_kdl(tab, ctx, src):
    """A standalone tab layout, for `zellij action new-tab --layout`."""
    return "\n".join([HEADER % src, "layout {",
        "    " + bars(ctx)[0], tab_body(tab, ctx, 4)]
        + (["    " + bars(ctx)[1]] if bars(ctx)[1] else []) + ["}"])

UNIT = """[Unit]
Description=Phosphor fleet mount - %(name)s (rclone sftp)
After=network-online.target

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p %(mp)s
ExecStart=%(rclone)s mount %(name)s:%(path)s %(mp)s --config %%h/.config/rclone/rclone.conf --sftp-skip-links --vfs-cache-mode writes --dir-cache-time 20s --attr-timeout 5s --timeout 30s --contimeout 10s
ExecStop=-%(fusermount)s -u %(mp)s
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""

DECK_UNIT = """[Unit]
Description=Phosphor Deck - keeps the zellij session up
After=network-online.target

[Service]
Type=oneshot
# zellij forks its server and exits. Without KillMode=process systemd
# cleans up the cgroup when the unit ends and takes the server with it.
KillMode=process
Environment=TERM=xterm-256color
# Panes inherit these: yazi and friends open files with the editor, and a
# pane zellij opens (Ctrl-p n, a split) runs the shell.
Environment="EDITOR=%(editor)s" "VISUAL=%(editor)s" "SHELL=%(shell)s"
# The logic lives in a generated script: ExecStart reinterprets $ and
# backslashes, and a long sh -c in there is fragile.
ExecStart=/bin/sh %%h/.local/share/phosphor/%(session)s-up.sh

[Install]
WantedBy=default.target
"""

DECK_UP = """#!/bin/sh
# GENERATED BY `phosphor gen` — don't edit by hand.
# Makes sure the deck session exists. deck.timer runs it every minute, so
# it's idempotent: a live session is left alone.
Z=%(zellij)s
S=%(session)s
s=$($Z list-sessions -n 2>/dev/null | grep "^$S " || true)
case "$s" in
  # a dead session stays in the resurrection cache and --create-background
  # would bring it back dead: delete it first
  *EXITED*) $Z delete-session "$S" >/dev/null 2>&1; s="" ;;
esac
# Browser access (web = true): the session is created shareable, and the
# web server (127.0.0.1 only; tailscale serve publishes it) kept running.
# `zellij web --status` exits 0 either way: read what it says.
if [ "%(web)s" = "1" ] && ! $Z web --status 2>/dev/null | grep -q online; then
  $Z web --start --daemonize >/dev/null 2>&1
fi
[ -n "$s" ] && exit 0
if [ "%(web)s" = "1" ]; then
  $Z --layout "$S" attach --create-background "$S" options --web-sharing on --web-server true || exit 1
else
  $Z --layout "$S" attach --create-background "$S" || exit 1
fi
# Floating panes only with notifier = true. In real use zellij 0.45.1 wedged
# its screen thread at 100%% when switching tabs after hiding them by id
# (-t). Cause unproven (see doc/manual/profile.md and issue #14); this loop
# still has to touch every tab here, unlike phosphor notify's own hider --
# every tab's floating pane genuinely starts visible (the layout's own
# default), so every one of them needs hiding once, right after start.
if [ "%(notifier)s" = "1" ]; then
  for i in 1 2 3 4 5 6 7 8 9 10; do
    n=$($Z -s "$S" action list-tabs 2>/dev/null | tail -n +2 | wc -l)
    [ "$n" -gt 0 ] && break
    sleep 1
  done
  for pass in 1 2; do
    sleep 2
    for id in $($Z -s "$S" action list-tabs 2>/dev/null | tail -n +2 | awk '{print $1}'); do
      $Z -s "$S" action hide-floating-panes -t "$id" >/dev/null 2>&1
    done
  done
fi
exit 0
"""

DECK_TIMER = """[Unit]
Description=Phosphor Deck - watchdog: brings the session back if it died

[Timer]
OnCalendar=*:0/1
AccuracySec=10s
Persistent=false

[Install]
WantedBy=timers.target
"""

def editor(ctx):
    return deckconf.editor(ctx.prof)

def units(ctx):
    sess = ctx.deck.get("session", "deck")
    out = {"%s.service" % sess: DECK_UNIT % {"zellij": resolve("zellij"), "session": sess,
                                            "editor": editor(ctx), "shell": deckconf.shell(ctx.prof)},
           "%s.timer" % sess: DECK_TIMER}
    import tunnels
    for t in deckconf.tunnels(ctx.prof):
        out[tunnels.unit_name(t["host"])] = tunnels.unit(t)
    for h in ctx.remotes():
        out["fleet-%s.service" % h["name"]] = UNIT % {
            "name": h["name"], "path": h["mount"],
            "mp": os.path.join(ctx.root, h["name"]),
            "rclone": resolve("rclone"), "fusermount": FUSERMOUNT}
    return out

def rclone_conf(ctx):
    """Each remote goes through the system's ssh, not rclone's own: that way
    it sees what `ssh HOST` sees (~/.ssh/config HostName, Port, User,
    IdentityFile, the agent, known_hosts). rclone's internal ssh reads none of
    it, so a machine that answered the wizard's ssh could still mount empty.
    ssh checks the host key itself, hence known_hosts_file = none; hashes are
    off because rclone would open one ssh connection per file for them."""
    blocks = []
    for h in ctx.remotes():
        tgt = h.get("ssh") or h["name"]
        if h.get("user") and "@" not in tgt:
            tgt = "%s@%s" % (h["user"], tgt)
        blocks.append("[%s]\ntype = sftp\n"
                      "ssh = ssh -o BatchMode=yes -o ServerAliveInterval=20 -o ConnectTimeout=10 %s\n"
                      "known_hosts_file = none\nshell_type = unix\n"
                      "md5sum_command = none\nsha1sum_command = none\n" % (h["name"], tgt))
    return "\n".join(blocks)

CONNECT = """#!/bin/sh
# GENERATED BY `phosphor gen` — don't edit by hand.
# This machine is a VIEWER: the session lives on %(brain)s.
# zellij's path is resolved ON THE BRAIN, where the home may differ, hence
# the login shell over there.
%(body)s"""
# ssh carries the mouse and touch; if it drops, run it again: the session
# never left the brain. mosh survives sleep and network changes but drops
# the mouse (it lacks SGR mouse mode), so it's opt-in: connect = "mosh".
# ssh exits 0 when you detach (Alt-x, Ctrl-q) and non-zero when the link
# drops (sleep, network change) or the deck is restarting: then retry.
CONNECT_SSH = ("[ -n \"$ZELLIJ\" ] && { echo \"already inside a zellij session: no deck inside the deck\"; exit 1; }\n"
               "while :; do\n"
               "  ssh -t -o ServerAliveInterval=15 -o ServerAliveCountMax=2 %(target)s '/bin/sh -lc \"exec %(command)s 2>/dev/null || exec zellij attach %(session)s\"' && break\n"
               "  echo \"[ lost the deck, reconnecting in 3s. Ctrl-C to stop ]\"; sleep 3\n"
               "done\n")
CONNECT_MOSH = ("if command -v mosh >/dev/null 2>&1; then\n"
                "  exec mosh %(target)s -- /bin/sh -lc 'exec %(command)s 2>/dev/null || exec zellij attach %(session)s'\n"
                "fi\n" + CONNECT_SSH)

ATTACH = """#!/bin/sh
# GENERATED BY `phosphor gen` — don't edit by hand.
# The deck lives on this machine: one word gets you in.
exec %(phosphor)s attach
"""

ZCONF   = os.path.join(HOME, ".config/zellij/config.kdl")
ZTHEME  = os.path.join(HOME, ".config/zellij/themes/phosphor.kdl")

def zellij_theme(name):
    """Same palette as our TUIs, so `theme` recolors the whole deck at once."""
    P = PALETTES[name]
    m = [("fg", "fg"), ("bg", "bg"), ("black", "bg"), ("red", "bad"),
         ("green", "ph"), ("yellow", "warn"), ("blue", "mute"), ("magenta", "bloom"),
         ("cyan", "bloom"), ("white", "fg"), ("orange", "warn")]
    body = "\n".join('        %-7s "%s"' % (k, hexc(P[v])) for k, v in m)
    return ("// GENERATED BY `phosphor gen` — don't edit by hand.\n"
            "// Palette %s, from `theme` in the profile.\n"
            "themes {\n    phosphor {\n%s\n    }\n}\n" % (name, body))

# The deck in a browser (web = true) is xterm.js: without this it draws on
# black whatever the palette, paper included. zellij's login box keeps its
# own colors: 0.45 hardcodes them in the page.
WEB_BEGIN = "// ── PHOSPHOR WEB: phosphor gen writes from here to END PHOSPHOR WEB, from theme in your profile."
WEB_END   = "// ── END PHOSPHOR WEB"

def web_block(name):
    P = PALETTES[name]
    m = [("background", "bg"), ("foreground", "fg"), ("cursor", "ph"), ("cursor_accent", "bg"),
         ("selection_background", "dim"), ("selection_foreground", "bloom"),
         ("black", "bg"), ("red", "bad"), ("green", "ph"), ("yellow", "warn"), ("blue", "mute"),
         ("magenta", "bloom"), ("cyan", "bloom"), ("white", "fg"),
         ("bright_black", "dim"), ("bright_red", "bad"), ("bright_green", "bloom"), ("bright_yellow", "warn"),
         ("bright_blue", "fg"), ("bright_magenta", "bloom"), ("bright_cyan", "bloom"), ("bright_white", "bloom")]
    body = "\n".join('        %s "%s"' % (k, hexc(P[v])) for k, v in m)
    # zellij 0.45 refuses a web client on a session that hasn't opted in
    # ("web_sharing" off by default): without this, `phosphor web on` never
    # actually attaches to a thing you can reach.
    return "\n".join([WEB_BEGIN, 'web_sharing "on"', "web_client {", '    font "monospace"', "    theme {",
                      body, "    }", "}", WEB_END])

def put_web(text, name):
    """(config with the web block rewritten, what happened): "updated", "same",
    "yours" (a web_client or a web_sharing of your own: left alone), or
    "stripped" (name None)."""
    pat = re.compile(r"\n*^%s$.*?^%s$\n?" % (re.escape(WEB_BEGIN), re.escape(WEB_END)), re.S | re.M)
    rest = pat.sub("\n", text) if pat.search(text) else text
    if name is None:
        return rest.rstrip("\n") + "\n", "stripped"
    if re.search(r"^\s*web_client\s*\{", rest, re.M) or re.search(r"^\s*web_sharing\s+", rest, re.M):
        return text, "yours"
    new = rest.rstrip("\n") + "\n\n" + web_block(name) + "\n"
    return new, ("same" if new == text else "updated")

# Tools the deck launches that take their own color from a config file:
# recolored the same way as zellij and the web client, from `theme`.
GEN_MARK = "# GENERATED BY `phosphor gen`"
YAZI_THEME_PATH = os.path.join(HOME, ".config/yazi/theme.toml")
YAZI_KEYMAP_PATH = os.path.join(HOME, ".config/yazi/keymap.toml")
BTOP_THEME_DIR  = os.path.join(HOME, ".config/btop/themes")
BTOP_THEME_PATH = os.path.join(BTOP_THEME_DIR, "phosphor.theme")
BTOP_CONF_PATH  = os.path.join(HOME, ".config/btop/btop.conf")

def yazi_theme(name):
    """yazi has one theme.toml, no separate slot for ours like zellij's
    themes/ dir -- the whole file is generated, palette in, when it's ours
    to write (see yazi_config)."""
    P = PALETTES[name]
    fg, dim, mute, ph, bloom, warn, bad, ruleC, bg = (
        hexc(P[k]) for k in ("fg", "dim", "mute", "ph", "bloom", "warn", "bad", "rule", "bg"))
    return ("%s -- don't edit by hand.\n"
            "# Palette %s, from `theme` in the profile.\n" % (GEN_MARK, name) +
            '[mgr]\n'
            'cwd = { fg = "%s" }\n' % bloom +
            'hovered = { fg = "%s", bg = "%s" }\n' % (bg, ph) +
            'preview_hovered = { underline = true }\n'
            'find_keyword  = { fg = "%s", bold = true }\n' % warn +
            'find_position = { fg = "%s", bold = true }\n' % bad +
            'marker_copied   = { fg = "%s", bg = "%s" }\n' % (ph, ph) +
            'marker_cut      = { fg = "%s", bg = "%s" }\n' % (bad, bad) +
            'marker_marked   = { fg = "%s", bg = "%s" }\n' % (warn, warn) +
            'marker_selected = { fg = "%s", bg = "%s" }\n' % (bloom, bloom) +
            'tab_active   = { fg = "%s", bg = "%s" }\n' % (bg, ph) +
            'tab_inactive = { fg = "%s", bg = "%s" }\n' % (fg, ruleC) +
            'border_symbol = "│"\n'
            'border_style  = { fg = "%s" }\n' % ruleC +
            '\n[status]\n'
            'separator_open  = ""\n'
            'separator_close = ""\n'
            'mode_normal = { fg = "%s", bg = "%s", bold = true }\n' % (bg, ph) +
            'mode_select = { fg = "%s", bg = "%s", bold = true }\n' % (bg, warn) +
            'mode_unset  = { fg = "%s", bg = "%s", bold = true }\n' % (bg, bad) +
            'progress_label  = { fg = "%s", bold = true }\n' % fg +
            'progress_normal = { fg = "%s", bg = "%s" }\n' % (ph, ruleC) +
            'progress_error  = { fg = "%s", bg = "%s" }\n' % (bad, ruleC) +
            '\n[filetype]\n'
            'rules = [\n'
            '  { mime = "image/*", fg = "%s" },\n' % bloom +
            '  { mime = "video/*", fg = "%s" },\n' % warn +
            '  { mime = "audio/*", fg = "%s" },\n' % warn +
            '  { mime = "application/zip", fg = "%s" },\n' % bad +
            '  { url  = "*/", fg = "%s" },\n' % ph +
            '  { url  = "*",  fg = "%s" },\n' % fg +
            ']\n')

# theme.toml existed before `phosphor gen` managed it (hand-written, p31
# only): adopted once, like SHIPPED_CONFIGS below, instead of overwritten
# blind or left mismatched with `theme` forever.
YAZI_SHIPPED = {
    "0b24a203dcfe441a4a1cb6cbccd9b9479f59df487959642261d1bffe1cfd6829",
}

def yazi_config(dry, changed, name):
    if not deckconf.exe("yazi"):
        return
    new = yazi_theme(name)
    if os.path.exists(YAZI_THEME_PATH):
        txt = open(YAZI_THEME_PATH).read()
        if txt.startswith(GEN_MARK):
            pass                      # already ours: safe to just update
        elif hashlib.sha256(txt.encode()).hexdigest() in YAZI_SHIPPED:
            if not dry:               # ours, not marked yet: adopt once, keep a copy
                open(YAZI_THEME_PATH + ".bak", "w").write(txt)
        elif txt != new:
            print(row(WARN, "yazi theme.toml", "yours, left alone",
                      note="phosphor gen only recolors the one it manages"))
            return
    write(YAZI_THEME_PATH, new, dry, changed)

def yazi_keymap():
    """The two keybindings phosphor adds to yazi, both on the hovered file,
    no shell tab needed: its contents onto every screen's clipboard
    (phosphor clip), or the file itself as a one-time link and QR
    (phosphor send). yazi's own `c` chord already copies the path, the
    url, the filename... `c t`/`c s` join it. The file goes in as yazi's own
    `%s` placeholder (escaped for us): its shell action passes no $1/$@."""
    return (GEN_MARK + " -- don't edit by hand.\n"
            "# Two added keybindings, next to yazi's own c-path/c-url copies:\n"
            "# the hovered file's contents onto every screen's clipboard (phosphor\n"
            "# clip), or the file itself as a one-time link and QR (phosphor send).\n"
            "\n[mgr]\n"
            "prepend_keymap = [\n"
            "\t{ on = [ \"c\", \"t\" ], run = 'shell \"%s clip %%s && sleep 1\" --block', " % PHOSPHOR +
            "desc = \"Copy the file's contents to every screen's clipboard\" },\n"
            "\t{ on = [ \"c\", \"s\" ], run = 'shell \"%s send %%s\" --block', " % PHOSPHOR +
            "desc = \"Send the file as a one-time link and QR\" },\n"
            "]\n")

def yazi_keymap_config(dry, changed):
    if not deckconf.exe("yazi"):
        return
    new = yazi_keymap()
    if os.path.exists(YAZI_KEYMAP_PATH):
        txt = open(YAZI_KEYMAP_PATH).read()
        if not txt.startswith(GEN_MARK) and txt != new:
            print(row(WARN, "yazi keymap.toml", "yours, left alone",
                      note="phosphor gen only adds the one binding it manages"))
            return
    write(YAZI_KEYMAP_PATH, new, dry, changed)

def btop_theme(name):
    """btop's own named theme file (~/.config/btop/themes/phosphor.theme):
    nothing else uses that name, so always ours to overwrite."""
    P = PALETTES[name]
    fg, dim, mute, ph, bloom, warn, bad, ruleC, bg = (
        hexc(P[k]) for k in ("fg", "dim", "mute", "ph", "bloom", "warn", "bad", "rule", "bg"))
    rows = [
        ("main_bg", bg), ("main_fg", fg), ("title", bloom), ("hi_fg", warn),
        ("selected_bg", ruleC), ("selected_fg", ph), ("inactive_fg", dim), ("graph_text", mute),
        ("meter_bg", ruleC), ("proc_misc", bloom),
        ("cpu_box", ruleC), ("mem_box", ruleC), ("net_box", ruleC), ("proc_box", ruleC), ("div_line", ruleC),
        ("temp_start", ph), ("temp_mid", warn), ("temp_end", bad),
        ("cpu_start", dim), ("cpu_mid", ph), ("cpu_end", warn),
        ("free_start", ruleC), ("free_mid", dim), ("free_end", ph),
        ("cached_start", dim), ("cached_mid", ph), ("cached_end", bloom),
        ("available_start", warn), ("available_mid", warn), ("available_end", bloom),
        ("used_start", dim), ("used_mid", ph), ("used_end", bad),
        ("download_start", dim), ("download_mid", ph), ("download_end", bloom),
        ("upload_start", warn), ("upload_mid", warn), ("upload_end", bloom),
        ("process_start", dim), ("process_mid", ph), ("process_end", warn),
    ]
    body = "\n".join('theme[%s]="%s"' % (k, v) for k, v in rows)
    return "%s -- don't edit by hand.\n# Palette %s, from `theme` in the profile.\n%s\n" % (GEN_MARK, name, body)

def btop_config(dry, changed, name):
    if not deckconf.exe("btop"):
        return
    write(BTOP_THEME_PATH, btop_theme(name), dry, changed)
    # btop.conf holds hundreds of settings unrelated to color: touch only
    # the one line that picks a theme, and only while it's still "Default"
    # (never set) or already ours -- a theme you picked on purpose stays.
    txt = open(BTOP_CONF_PATH).read() if os.path.exists(BTOP_CONF_PATH) else ""
    m = re.search(r'^color_theme\s*=\s*"([^"]*)"', txt, re.M)
    current = m.group(1) if m else None
    if current not in (None, "", "Default", "phosphor"):
        print(row(WARN, "btop.conf", "keeps your own \"%s\" theme" % current,
                  note='color_theme = "phosphor" in btop.conf to switch'))
        return
    line = 'color_theme = "phosphor"'
    if m:
        new_txt = txt[:m.start()] + line + txt[m.end():]
    elif txt:
        new_txt = txt.rstrip("\n") + "\n" + line + "\n"
    else:
        new_txt = line + "\n"
    write(BTOP_CONF_PATH, new_txt, dry, changed)

# ctop only ever offers black/white plus -i to invert them: no palette to
# match, but paper's white background is a better fit inverted.
def ctop_extra_args(name):
    return ["-i"] if name == "paper" else []

# config.kdl as earlier versions installed it: a copy nobody touched gets the
# new one (Alt-r and Alt-n came in 0.2); an edited one is left alone.
SHIPPED_CONFIGS = {
    "a7183382a11d247489eb06e82c81f7596dd758701cac567d288d0af33f36bcc3",
    "11bb8eafb51fae74b4a1bcda41ca456d835e4e6d4d675091a83d56a0c9340f70",   # dev, with Alt-e
    "cb6486cc9d7c9c842470c420eded4c7e3c23db1394f52a743cb652923cebfc5e",   # dev, Alt-r and Alt-n
}

def zellij_config(dry, changed, prof=None, theme="p31"):
    """config.kdl belongs to the user. Installed when there's none, replaced
    only while it is exactly what an earlier version installed, and otherwise
    only the part between the PHOSPHOR KEYS markers is rewritten, from [keys]."""
    import hashlib, shortcuts
    new = open(share("zellij-config.kdl")).read()
    if not os.path.exists(ZCONF):
        write(ZCONF, put_web(shortcuts.put(new, prof)[0], theme)[0], dry, changed)
        return
    txt = open(ZCONF).read()
    # with the keys block back at the defaults and no web block, is the rest a copy we shipped?
    plain = put_web(shortcuts.put(txt, None)[0], None)[0]
    if plain != new and hashlib.sha256(plain.encode()).hexdigest() in SHIPPED_CONFIGS:
        if not dry: open(ZCONF + ".bak", "w").write(txt)
        write(ZCONF, put_web(shortcuts.put(new, prof)[0], theme)[0], dry, changed)
        print(row(OK, "config.kdl", ("would update" if dry else "updated") + ": the one Phosphor installed",
                  note="" if dry else "backup: config.kdl.bak"))
        return
    out, what = shortcuts.put(txt, prof)
    # the web block only goes where the deck already keeps its keys
    web = put_web(out, theme) if what != "no markers" else (out, "no markers")
    if what == "updated" or web[1] == "updated":
        write(ZCONF, web[0], dry, changed)
        print(row(OK, "config.kdl", ("would write" if dry else "wrote") + " "
                  + " and ".join(x for x, w in (("the deck's keys, from [keys]", what), ("the browser's colors", web[1]))
                                 if w == "updated"),
                  note="the rest of the file untouched"))
    elif what == "no markers":
        print(row(WARN, "config.kdl", "yours, without the deck's keys",
                  note="phosphor shortcuts --kdl: paste it inside keybinds { }"))
    else:
        print(row(OK, "config.kdl", "yours, left alone"))
    if re.search(r"^\s*phosphor\s*\{", txt, re.M):
        print(row(AMB, "config.kdl", "defines its own phosphor theme",
                  note="it hides the generated one: remove it"))

def local_links(ctx, dry, changed):
    """The brain's disks show up under mount_root/<brain>/ as links, named
    like phosphor path expects them: / is root, ~ is home, /mnt/X is X."""
    lh = ctx.local()
    for m in (lh or {}).get("mounts", []):
        link = os.path.join(ctx.root, lh["name"], deckconf.label(m))
        dest = os.path.expanduser(m)
        name = "%s/%s" % (lh["name"], deckconf.label(m))
        if os.path.islink(link) and os.readlink(link) == dest:
            print(row(OK, name, "unchanged")); continue
        if os.path.exists(link) and not os.path.islink(link):
            print(row(AMB, name, "exists and isn't a link", note="left alone")); continue
        changed.append(link)
        if dry:
            print(row(AMB, name, "WOULD CHANGE")); continue
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link): os.remove(link)
        os.symlink(dest, link)
        print(row(OK, name, "-> " + dest))

def write(path, content, dry, changed):
    old = open(path).read() if os.path.exists(path) else None
    if old == content:
        print(row(OK, os.path.basename(path), "unchanged")); return
    changed.append(path)
    if dry:
        print(row(AMB, os.path.basename(path), "WOULD CHANGE")); return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(content)
    print(row(OK, os.path.basename(path), "written" if old is None else "updated"))

def run(prof, src, dry=False):
    if not prof:
        print("  no profile"); return 1
    ctx, changed = Ctx(prof), []
    print()
    print(BLOOM + "  phosphor gen" + RST + DIM + ("  (dry-run)" if dry else "") + RST)
    print(DIM + "  source: " + src + RST)

    if not ctx.is_brain():
        b = ctx.brain()
        lh = ctx.local()
        print("\n" + rule("viewer"))
        rol = (lh or {}).get("role", "?")
        print(row(OK, "this machine", "%s (%s)" % ((lh or {}).get("name", "?"), rol)))
        if not b:
            print(row(BAD, "no brain", "no host has role = brain"))
            print(); return 1
        print(row(OK, "brain", b["name"], note="the session lives there"))
        print("  " + DIM + "no session or mounts here: the brain has them" + RST)
        tgt = ("%s@%s" % (b["user"], b.get("ssh") or b["name"])) if b.get("user") else (b.get("ssh") or b["name"])
        v = {"brain": b["name"], "target": tgt, "session": ctx.deck.get("session", "deck"),
             "command": ctx.deck.get("command", "deck")}
        body = CONNECT_MOSH if ctx.deck.get("connect", "ssh") == "mosh" else CONNECT_SSH
        script = CONNECT % dict(v, body=body % v)
        dest = os.path.join(HOME, ".local/bin", ctx.deck.get("session", "deck"))
        print("\n" + rule("connect command"))
        write(dest, script, dry, changed)
        if not dry and changed:
            os.chmod(dest, 0o755)
        print("\n" + rule("summary"))
        if changed and not dry:
            print("  " + OK + " ready. Connect with: " + PH + os.path.basename(dest) + RST)
        elif dry:
            print("  " + AMB + " %d files would change." % len(changed) + RST)
        else:
            print("  " + OK + " all up to date")
        print()
        return 0

    cmdname = ctx.deck.get("command", "deck")
    if cmdname == os.path.basename(PHOSPHOR):
        cmdname = "deck"                      # never shadow phosphor itself
    print("\n" + rule("the %s command" % cmdname))
    here = os.path.join(HOME, ".local/bin", cmdname)
    write(here, ATTACH % {"phosphor": PHOSPHOR, "session": ctx.deck.get("session", "deck")}, dry, changed)
    if not dry and os.path.exists(here):
        os.chmod(here, 0o755)

    want = ctx.deck.get("shell")
    if want and not deckconf.exe(want):
        print(row(WARN, "shell", "%s isn't installed" % want, note="panes use " + deckconf.shell(prof)))
    ed = editor(ctx).split()[0] if editor(ctx) else ""
    if ctx.deck.get("editor") and not deckconf.exe(ed):
        print(row(WARN, "editor", "%s isn't installed" % ed, note="phosphor store has micro and helix"))

    print("\n" + rule("session layout"))
    write(os.path.join(ZDIR, "%s.kdl" % ctx.deck.get("session", "deck")),
          deck_kdl(prof, ctx, src), dry, changed)

    print("\n" + rule("per-tab layouts"))
    for tab in deckconf.effective_tabs(prof):
        write(os.path.join(ZDIR, "tab-%s.kdl" % tab["name"].lower()),
              tab_kdl(tab, ctx, src), dry, changed)

    print("\n" + rule("zellij theme and config"))
    write(ZTHEME, zellij_theme(theme_name(prof)), dry, changed)
    zellij_config(dry, changed, prof, theme_name(prof))

    print("\n" + rule("the tools' own color"))
    yazi_config(dry, changed, theme_name(prof))
    yazi_keymap_config(dry, changed)
    btop_config(dry, changed, theme_name(prof))
    if not deckconf.exe("yazi") and not deckconf.exe("btop"):
        print(row(DIM + "·" + RST, "yazi, btop", "neither installed", note="gping and ctop take theirs on the command line"))

    print("\n" + rule("this machine's disks"))
    local_links(ctx, dry, changed)

    print("\n" + rule("systemd units"))
    for name, body in units(ctx).items():
        write(os.path.join(UDIR, name), body, dry, changed)
    if not ctx.remotes():
        print(row(DIM + "·" + RST, "no remote hosts", "nothing to mount"))

    sess_name = ctx.deck.get("session", "deck")
    up = os.path.join(HOME, ".local/share/phosphor", "%s-up.sh" % sess_name)
    write(up, DECK_UP % {"zellij": resolve("zellij"), "session": sess_name,
                     "notifier": "1" if ctx.deck.get("notifier", False) else "0",
                     "web": "1" if ctx.deck.get("web", False) else "0"}, dry, changed)
    if not dry and os.path.exists(up):
        os.chmod(up, 0o755)

    print("\n" + rule("rclone remotes"))
    rc = rclone_conf(ctx)
    if rc: write(os.path.join(HOME, ".config/rclone/rclone.conf"), rc, dry, changed)
    # rclone reads its config once, at start: running mounts need a restart to see it
    if not dry and any(str(c).endswith("rclone.conf") for c in changed):
        subprocess.run(["systemctl", "--user", "try-restart", "fleet-*.service"], capture_output=True)
        print(row(OK, "fleet mounts", "restarted with the new rclone.conf"))

    print("\n" + rule("summary"))
    if not changed:
        print("  " + OK + " " + PH + "all up to date" + RST)
    elif dry:
        print("  " + AMB + " %d files would change. Run without --dry-run." % len(changed) + RST)
    else:
        print("  " + OK + " %d files written." % len(changed))
    if changed and not dry:
        live = subprocess.run([resolve("zellij"), "list-sessions", "-n"], capture_output=True,
                              text=True).stdout.startswith(ctx.deck.get("session", "deck") + " ")
        if live:
            print("  " + PH + "next: phosphor restart" + RST + DIM + "   applies this to the running deck" + RST)
        else:
            print("  " + PH + "next: phosphor up" + RST + DIM + "   starts the deck, mounts included" + RST)
    print()
    return 0
