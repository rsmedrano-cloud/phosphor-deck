#!/usr/bin/env python3
"""A workspace's folder, files and tab, without touching the live deck.

    python3 tests/workspace-check.py

Names from note titles, the files for each shape, never overwriting what's
there, a tab entry the profile parses and gen can lay out, and the CLI with
--folder-only on a scratch profile.
"""
import os, shutil, subprocess, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import workspace as ws, keep, gen, deckconf, notes

fail = []
def check(what, cond):
    if not cond: fail.append(what)

check("slug", ws.slug("Índice de conversaciones de IA por máquina") == "indice-de-conversaciones-de-ia")
check("slug of nothing", ws.slug("¿?") == "")

d = tempfile.mkdtemp()
base = os.path.join(d, "shop")
two = ws.plan("shop", base, "two", ["frontend", "backend"], "claude", brief="## x · idea · me · A shop\n")
check("two: files", sorted(two) == ["AGENTS.md", "BRIEF.md", "NOTES.md", "backend/AGENTS.md",
                                     "backend/CLAUDE.md", "frontend/AGENTS.md", "frontend/CLAUDE.md"])
check("two: each knows its part", "**backend**" in two["backend/AGENTS.md"] and "frontend" in two["backend/AGENTS.md"])
check("two: reads the brief", "BRIEF.md" in two["frontend/AGENTS.md"])
check("the notebook is a notebook", notes.split(two["NOTES.md"])[1] == [])
one = ws.plan("solo", base, "one", [], "codex")
check("one, codex: no CLAUDE.md, no brief", sorted(one) == ["AGENTS.md", "NOTES.md"])

os.makedirs(base)
open(os.path.join(base, "AGENTS.md"), "w").write("mine\n")
written, kept = ws.write_files(base, two)
check("never overwrites", open(os.path.join(base, "AGENTS.md")).read() == "mine\n" and kept == ["AGENTS.md"])
check("writes the rest", len(written) == 6 and os.path.exists(os.path.join(base, "backend/CLAUDE.md")))
check("git", os.path.isdir(os.path.join(base, ".git")) or not shutil.which("git"))   # the CI image has no git

for shape, parts, n in (("one", [], 1), ("two", ["frontend", "backend"], 2), ("shell", [], 2)):
    spec = ws.tab_spec("shop", base, shape, parts, "claude")
    blk = keep.block(spec["name"], spec["panes"], spec.get("split"))
    prof = deckconf.tomllib.loads(keep.put("[deck]\nsession = \"t\"\n", spec["name"], blk))
    tab = prof["tabs"][0]
    check(shape + ": parses", tab["name"] == "SHOP" and len(tab["panes"]) == n)
    kdl = gen.tab_kdl(tab, gen.Ctx(prof), "test")
    check(shape + ": lays out in its folder", ('cwd "%s' % base) in kdl)
check("resumes on restart", "--continue" in ws.tab_spec("s", base, "one", [], "claude")["panes"][0]["args"][1])
check("first message quoted", "'it'\"'\"'s'" in ws.assistant_line("claude", "it's"))

# aider (#33): a real --assistant choice, its own --restore-chat-history
# resume, and --message answering once then handing off to a normal
# interactive aider (it has no flag for "first message, stay open").
check("aider is a known assistant", "aider" in ws.FIRST)
check("aider resumes with its own flag, not --continue",
      "--restore-chat-history" in ws.tab_spec("s", base, "one", [], "aider")["panes"][0]["args"][1])
first = ws.assistant_line("aider", "it's")
check("aider's first message: one-shot --message, --yes-always so it never waits on a prompt",
      "aider --message 'it'\"'\"'s' --yes-always" in first)
check("...then hands off to a normal interactive aider restoring that exchange",
      first.endswith("; exec aider --restore-chat-history"))
import newtab
check("aider is in the + menu's assistant list too", "aider" in dict(newtab.ASSISTANTS))
chat_line = notes.assistant_first_cmd("aider", '"$(cat /tmp/x.md)"')
check("notes.py's chat() builds the same one-shot-then-handoff line for aider",
      chat_line == 'aider --message "$(cat /tmp/x.md)" --yes-always; exec aider --restore-chat-history')

prof = os.path.join(d, "deck.toml")
open(prof, "w").write('[deck]\nprojects = "%s"\n\n[[tabs]]\nname = "SHOP"\npanes = [ {} ]\n' % d)
env = dict(os.environ, PHOSPHOR_PROFILE=prof, PHOSPHOR_NOTES=os.path.join(d, "n.md"))
env.pop("ZELLIJ", None)
notes.append(env["PHOSPHOR_NOTES"], "idea", "claude", "Un índice de charlas", "- por máquina")
def run(*a):
    return subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "workspace"] + list(a),
                          env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
r = run("new", "--note", "índice", "--shape", "one", "--assistant", "claude", "--folder-only")
made = os.path.join(d, "un-indice-de-charlas")
check("from a note: named after it", r.returncode == 0 and os.path.isfile(os.path.join(made, "BRIEF.md")))
check("from a note: the brief is the note", "Un índice de charlas" in open(os.path.join(made, "BRIEF.md")).read())
r = run("new", "--note", "nothing like it", "--folder-only")
check("an unknown note stops", r.returncode == 1 and "no note" in r.stdout)
r = run("new", "shop", "--shape", "one", "--assistant", "claude")
check("a tab name that isn't this workspace stops", r.returncode == 1 and "already has" in r.stdout)
check("list", "un-indice-de-charlas" in run("list").stdout)

# git_status()/dirty_workspaces() (#36): dirty and ahead/behind, against a
# real git repo and a real upstream -- not mocked, this is exactly the
# kind of thing a mock could get subtly wrong.
if shutil.which("git"):
    gbase = os.path.join(d, "gitws")
    os.makedirs(gbase)
    def g(*a):
        subprocess.run(["git", "-C", gbase] + list(a), capture_output=True)
    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "t")
    open(os.path.join(gbase, "f.txt"), "w").write("1\n")
    g("add", "f.txt"); g("commit", "-q", "-m", "one")
    check("git_status: clean, no upstream", ws.git_status(gbase) == (False, 0, 0))

    origin = os.path.join(d, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", origin], capture_output=True)
    g("remote", "add", "origin", origin)
    g("push", "-q", "-u", "origin", "HEAD:main")
    check("git_status: clean, pushed, up to date with its upstream", ws.git_status(gbase) == (False, 0, 0))

    open(os.path.join(gbase, "f.txt"), "w").write("2\n")
    g("commit", "-q", "-am", "two")
    check("git_status: one local commit ahead, not yet pushed", ws.git_status(gbase) == (False, 1, 0))

    open(os.path.join(gbase, "f.txt"), "w").write("3\n")
    check("git_status: dirty on top of ahead", ws.git_status(gbase) == (True, 1, 0))

    check("git_status: not a git repo at all", ws.git_status(d) is None)

    dws = os.path.join(d, "dirty-workspaces-root")
    shop = os.path.join(dws, "shop")
    os.makedirs(shop)
    files = {"NOTES.md": "# shop notes\n", "AGENTS.md": "# shop\n"}
    real_root = ws.root
    ws.root = lambda prof=None: dws
    try:
        written, kept = ws.write_files(shop, files)
        check("write_files() commits the scaffold itself: not one of the checks a dirty git repo would be otherwise",
              ws.git_status(shop) == (False, 0, 0))
        check("dirty_workspaces: a freshly created workspace is clean, not flagged from day one",
              ws.dirty_workspaces() == [])
        open(os.path.join(shop, "x.txt"), "w").write("wip\n")
        check("dirty_workspaces: an untracked file made afterward makes it show up",
              ws.dirty_workspaces() == [("shop", True, 0, 0)])
    finally:
        ws.root = real_root

if fail:
    print("FAIL: " + "; ".join(fail)); sys.exit(1)
print("ok")
