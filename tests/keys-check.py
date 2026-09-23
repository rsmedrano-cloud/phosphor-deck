#!/usr/bin/env python3
"""The deck's keys: [keys] in the profile, and what gen may touch.

    python3 tests/keys-check.py

gen rewrites only the block between the PHOSPHOR KEYS markers: a bind of
your own outside it survives, a config.kdl without markers is left alone, an
untouched config an earlier version shipped is updated with your keys kept.
"""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import shortcuts as S, gen as G
fails = []
def need(what, ok):
    if not ok: fails.append(what)

# keys typed on a terminal, as zellij spells them
need("parse", [S.parse(x) for x in (b"\x1br", b"\x12", b"\x1b[1;3D", b"\x1b[1;7C", b"\x1b\x12", b"a", b"\x1b", b"\x7f")]
     == ["Alt r", "Ctrl r", "Alt Left", "Ctrl Alt Right", "Ctrl Alt r", "?", None, ""])
# conflicts: another deck action, a tool, nothing
k = S.current({})
need("conflict with the deck", S.conflicts(k, "edit", "Alt z") == (["zoom"], []))
need("conflict with matterhorn", S.conflicts(k, "edit", "Alt e") == ([], ["matterhorn"]))
need("Ctrl-q stays leave's", S.conflicts(k, "zoom", "Ctrl q")[0] == ["leave (Ctrl-q)"])
need("a free key", S.conflicts(k, "edit", "Alt y") == ([], []))
# [keys] in the profile, written as text
t = S.set_text('[deck]\ntheme = "p31"\n\n[[tabs]]\nname = "A"\npanes = [ {} ]\n', "edit", "Alt y")
t = S.set_text(t, "zoom", "")
t = S.set_text(t, "edit", "Alt i")
import tomllib
got = S.current(tomllib.loads(t))
need("[keys] round trip", got["edit"] == "Alt i" and got["zoom"] == "" and got["leave"] == "Alt x")
need("an empty key binds nothing", "ToggleFocusFullscreen" not in S.block(tomllib.loads(t)))

# gen and config.kdl, in a throwaway HOME
home = tempfile.mkdtemp()
conf = os.path.join(home, ".config/zellij/config.kdl")
prof = os.path.join(home, ".config/phosphor/deck.toml")
os.makedirs(os.path.dirname(conf)); os.makedirs(os.path.dirname(prof))
open(prof, "w").write('[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n\n[[tabs]]\nname = "A"\n'
                      'panes = [ {} ]\n\n[keys]\nedit = "Alt y"\n')
def gen():
    subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "gen"], capture_output=True,
                   env=dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof, ZELLIJ_SOCKET_DIR=os.path.join(home, "s")))
    return open(conf).read()

# the config.kdl 0.1.x installed (no git here: CI images don't have it)
open(conf, "w").write(open(os.path.join(ROOT, "tests/fixtures/zellij-config-0.1.kdl")).read())
c = gen()
need("a shipped config is updated", "PHOSPHOR KEYS" in c and os.path.exists(conf + ".bak"))
need("with the profile's keys", 'bind "Alt y"' in c and 'bind "Alt r"' not in c)

c = open(conf).read().replace('    unbind "Ctrl g"', '    unbind "Ctrl g"\n    locked { bind "Alt u" { GoToTab 3; } }  // mine')
open(conf, "w").write(c)
open(prof, "a").write('zoom = "Ctrl Alt z"\n')
c = gen()
need("a bind of my own survives", '// mine' in c)
need("the block follows [keys]", 'bind "Ctrl Alt z"' in c and 'bind "Alt z"' not in c)
need("only one block", c.count("PHOSPHOR KEYS:") == 1)

need("the browser gets the palette", c.count("PHOSPHOR WEB:") == 1 and "web_client {" in c)
need("and web_sharing, or the session refuses the web client", 'web_sharing "on"' in c)
c2 = gen()
need("the web block once, however many gens", c2.count("PHOSPHOR WEB:") == 1 and c2 == c)
import re as _re
mine = _re.sub(r"// ── PHOSPHOR WEB:.*?// ── END PHOSPHOR WEB\n", 'web_client {\n    font "Iosevka"\n}\n', c, flags=_re.S)
open(conf, "w").write(mine)
need("a web_client of my own is left alone", gen() == mine)
mine_sharing = _re.sub(r"// ── PHOSPHOR WEB:.*?// ── END PHOSPHOR WEB\n", 'web_sharing "off"\n', c, flags=_re.S)
open(conf, "w").write(mine_sharing)
need("a web_sharing of my own is left alone too", gen() == mine_sharing)
for t in ("p31", "p3", "p4", "paper"):
    need("web block for " + t, G.web_block(t).count('"#') == 22)

open(conf, "w").write("keybinds {\n}\n")
need("no markers: untouched", gen() == "keybinds {\n}\n")

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
