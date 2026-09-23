#!/usr/bin/env python3
"""A file's contents (or the file itself) from inside yazi -- no shell tab
needed.

    python3 tests/yazi-keymap-check.py

`phosphor gen` writes ~/.config/yazi/keymap.toml with two added bindings,
next to yazi's own `c`-path/`c`-url copies: `c t` shells out to `phosphor
clip` on the hovered file (its contents, onto every screen's clipboard),
`c s` to `phosphor send` (the file itself, as a one-time link and QR). A
keymap.toml of your own is left alone, same as theme.toml.
"""
import os, subprocess, sys, tempfile, tomllib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import gen as G

fails = []
def need(what, ok):
    if not ok: fails.append(what)

new = G.yazi_keymap()
need("marked as generated", new.startswith(G.GEN_MARK))
data = tomllib.loads(new)
bindings = {tuple(b["on"]): b for b in data["mgr"]["prepend_keymap"]}
need("exactly two bindings added", len(bindings) == 2)

clip_b = bindings.get(("c", "t"))
need("c t is bound", clip_b is not None)
need("c t shells out to phosphor clip on the hovered file",
     clip_b and G.PHOSPHOR + " clip" in clip_b["run"] and ' %s' in clip_b["run"] and '$1' not in clip_b["run"])
need("c t runs blocking, so the confirmation is visible", clip_b and "--block" in clip_b["run"])

send_b = bindings.get(("c", "s"))
need("c s is bound", send_b is not None)
need("c s shells out to phosphor send on the hovered file",
     send_b and G.PHOSPHOR + " send" in send_b["run"] and ' %s' in send_b["run"] and '$1' not in send_b["run"])
need("absolute path: the zellij server has no ~/.local/bin (yazi exited 127)",
     os.path.isabs(G.PHOSPHOR) and '"phosphor ' not in new and "'shell \"phosphor" not in new)
need("c s runs blocking, so the link/QR are visible", send_b and "--block" in send_b["run"])

home = tempfile.mkdtemp()
prof = os.path.join(home, ".config/phosphor/deck.toml")
os.makedirs(os.path.dirname(prof))
os.makedirs(os.path.join(home, ".config/yazi"))
os.makedirs(os.path.join(home, ".local/bin"))
stub = os.path.join(home, ".local/bin/yazi")
open(stub, "w").write("#!/bin/sh\nexit 0\n")
os.chmod(stub, 0o755)
open(prof, "w").write(
    '[deck]\ntheme = "p31"\n\n[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n\n'
    '[[tabs]]\nname = "A"\npanes = [ {} ]\n')

def run_gen():
    subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "gen"],
                   capture_output=True, env=dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof))

keymap_path = os.path.join(home, ".config/yazi/keymap.toml")

run_gen()
need("keymap.toml written", os.path.exists(keymap_path))
need("matches what yazi_keymap() builds", open(keymap_path).read() == new)

# re-running gen is a no-op (idempotent, same as theme.toml)
before = os.path.getmtime(keymap_path)
run_gen()
need("unchanged on a second gen", os.path.getmtime(keymap_path) == before)

# a keymap.toml of your own survives
open(keymap_path, "w").write("# mine\n[mgr]\nkeymap = []\n")
run_gen()
need("a keymap.toml of your own is left alone", open(keymap_path).read() == "# mine\n[mgr]\nkeymap = []\n")

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("ok")
