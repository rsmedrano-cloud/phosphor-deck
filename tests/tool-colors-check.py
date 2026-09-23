#!/usr/bin/env python3
"""Every tool follows `theme`, not just zellij and the web client.

    python3 tests/tool-colors-check.py

yazi's theme.toml and btop's phosphor.theme change with the palette; a
theme.toml or color_theme gen didn't write is left alone; gping and ctop
get their color on the command line.
"""
import hashlib, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import gen as G
fails = []
def need(what, ok):
    if not ok: fails.append(what)

for t in ("p31", "p3", "p4", "paper"):
    need("yazi theme for " + t, G.yazi_theme(t).startswith(G.GEN_MARK))
    need("btop theme for " + t, G.btop_theme(t).count("theme[") > 30)
need("themes differ by palette", G.yazi_theme("p31") != G.yazi_theme("p3"))
need("ctop only inverts for paper", G.ctop_extra_args("paper") == ["-i"] and G.ctop_extra_args("p31") == [])

home = tempfile.mkdtemp()
prof = os.path.join(home, ".config/phosphor/deck.toml")
os.makedirs(os.path.dirname(prof))
os.makedirs(os.path.join(home, ".config/yazi"))
os.makedirs(os.path.join(home, ".config/btop/themes"))
open(os.path.join(home, ".config/btop/btop.conf"), "w").close()

# stub binaries: CI images don't ship yazi/btop, but deckconf.exe() checks
# ~/.local/bin/<name> before falling back to PATH, so a fake one there is
# enough for gen to believe the tool is installed and manage its theme.
os.makedirs(os.path.join(home, ".local/bin"))
for tool in ("yazi", "btop"):
    stub = os.path.join(home, ".local/bin", tool)
    open(stub, "w").write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)

def write_profile(theme, extra_tab=""):
    open(prof, "w").write(
        '[deck]\ntheme = "%s"\n\n[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n\n'
        '[[tabs]]\nname = "A"\npanes = [ {} ]\n%s' % (theme, extra_tab))

def run_gen():
    subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "gen"],
                   capture_output=True, env=dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof))

yazi_path = os.path.join(home, ".config/yazi/theme.toml")
btop_theme_path = os.path.join(home, ".config/btop/themes/phosphor.theme")
btop_conf_path = os.path.join(home, ".config/btop/btop.conf")

# a theme.toml written by an earlier, unmarked version of this feature is adopted once
shipped = open(os.path.join(ROOT, "tests/fixtures/yazi-theme-p31-shipped.toml")).read()
need("fixture matches the shipped hash gen.py knows",
     hashlib.sha256(shipped.encode()).hexdigest() in G.YAZI_SHIPPED)
open(yazi_path, "w").write(shipped)
write_profile("p31")
run_gen()
need("adopted quietly, backed up", os.path.exists(yazi_path + ".bak"))
need("marked as generated now", open(yazi_path).read().startswith(G.GEN_MARK))
need("btop theme written", os.path.exists(btop_theme_path))
need("btop.conf wired to phosphor", 'color_theme = "phosphor"' in open(btop_conf_path).read())

# switching theme recolors both, without re-asking
write_profile("p3")
before = open(yazi_path).read()
run_gen()
after = open(yazi_path).read()
need("amber recolors yazi", before != after and "#FFCC4D" in after)
need("amber recolors btop", "#FFCC4D" in open(btop_theme_path).read())

# a theme.toml of your own, and a btop theme you picked, survive
open(yazi_path, "w").write("# mine\n[mgr]\ncwd = { fg = \"#FF00FF\" }\n")
open(btop_conf_path, "w").write('color_theme = "Nord"\n')
run_gen()
need("a yazi theme of your own is left alone", open(yazi_path).read() == "# mine\n[mgr]\ncwd = { fg = \"#FF00FF\" }\n")
need("a btop theme of your own is left alone", 'color_theme = "Nord"' in open(btop_conf_path).read())

# gping and ctop take theirs on the layout's command line
write_profile("paper", '\n[[tabs]]\nname = "SYS"\npanes = [ { cmd = "gping", args = ["@hosts"] }, { cmd = "ctop" } ]\n')
run_gen()
kdl = open(os.path.join(home, ".config/zellij/layouts/tab-sys.kdl")).read()
need("gping gets a color", "--color" in kdl)
need("ctop inverts for paper", '"-i"' in kdl)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
