"""A deck for each kind of screen: [screens.KIND] (lib/kinds.py).

- a kind's layout has only its tabs, in its order, lands where it says,
  and carries no floating panes; its graphs and theme reach its panes;
- `phosphor gen --dry-run` writes that layout and the kind's zellij theme;
- a kind without a block, or no kind at all, is the deck's own session;
- the phone kit says `--screen phone`, `screen --as eink` says eink, and
  the brain's `deck` hands its arguments to `phosphor attach`;
- `phosphor screens` finds a client of any of those sessions, and says which;
- --live: a real, throwaway zellij makes the kind's session the way attach
  does, and its panes see PHOSPHOR_SCREEN, PHOSPHOR_THEME, PHOSPHOR_GRAPHS.

Never the live deck: its own HOME and zellij socket dir.
"""
import os, shutil, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
PHOSPHOR = os.path.join(ROOT, "phosphor")

HOME = tempfile.mkdtemp(prefix="kinds-")
os.makedirs(os.path.join(HOME, ".config/phosphor"))
PROF = os.path.join(HOME, ".config/phosphor/deck.toml")
open(PROF, "w").write("""
[deck]
session = "probe"
theme = "p31"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "SYS"
panes = [{ cmd = "gping", args = ["127.0.0.1"] }]

[[tabs]]
name = "NOTES"
panes = [{ cmd = "" }]

[[tabs]]
name = "COMMS"
panes = [{ cmd = "" }]

[screens.phone]
tabs = ["NOTES", "SYS"]
land = "SYS"
graphs = "blocks"

[screens.eink]
theme = "paper"

[screens.Bad-Name]
tabs = ["SYS"]
""")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
ENV.update(HOME=HOME, PHOSPHOR_PROFILE=PROF, XDG_RUNTIME_DIR=os.path.join(HOME, "run"),
           ZELLIJ_SOCKET_DIR=os.path.join(HOME, "sock"), XDG_CACHE_HOME=os.path.join(HOME, ".cache"),
           PHOSPHOR_CACHE=os.path.join(HOME, ".cache/phosphor"), TERM="xterm-256color")
for d in ("run", "sock"):
    os.makedirs(os.path.join(HOME, d), mode=0o700)
os.environ.clear(); os.environ.update(ENV)

import deckconf, gen, kinds, phone, screens
fails = 0
def check(what, ok, detail=""):
    global fails
    print(("  ok   " if ok else "  FAIL ") + what + ("" if ok else "\n       " + str(detail)[:400]))
    fails += 0 if ok else 1

prof, _ = deckconf.load()

# 1. which kinds, which session
check("well-formed kinds only", list(kinds.kinds(prof)) == ["phone", "eink"], kinds.kinds(prof))
check("a bad kind name is a problem", any(k == "Bad-Name" for k, _ in kinds.problems(prof)), kinds.problems(prof))
check("phone gets its own session", kinds.session(prof, "phone") == "probe-phone")
check("an unknown kind gets the deck's", kinds.session(prof, "tablet") == "probe")
check("no kind gets the deck's", kinds.session(prof, "") == "probe")
check("--screen is read either way", kinds.arg(["--screen", "Phone"]) == ("phone", [])
      and kinds.arg(["--screen=eink", "x"]) == ("eink", ["x"]))

# 2. the kind's layout
sc = gen.Ctx(dict(prof, deck=kinds.deck(prof, "phone")))
kdl = gen.deck_kdl(prof, sc, "test", kinds.tabs(prof, "phone"), kinds.land(prof, "phone"), floating=False)
check("only its tabs, in its order", kdl.index('tab name="NOTES"') < kdl.index('tab name="SYS"')
      and 'tab name="COMMS"' not in kdl, kdl)
check("lands on land", 'tab name="SYS" focus=true' in kdl and 'tab name="NOTES" focus=true' not in kdl, kdl)
check("no floating panes", "floating_panes" not in kdl, kdl)
check("its graphs reach gping (-s)", '"-s"' in kdl, kdl)
check("eink: every tab, the deck's graphs", [t["name"] for t in kinds.tabs(prof, "eink")] == ["SYS", "NOTES", "COMMS"])
check("eink: its theme", kinds.theme(prof, "eink") == "paper" and kinds.zellij_theme(prof, "eink") == "phosphor-paper")
check("phone: the deck's theme", kinds.theme(prof, "phone") == "p31")

# skip: panes a kind leaves out (the SYS row of pulse + adjutant, as shipped)
sk = {"tabs": [
    {"name": "SYS", "panes": [
        {"split": "cols", "size": 18, "panes": [{"cmd": "phosphor pulse"},
                                                 {"cmd": "phosphor adjutant", "size": 34}]},
        {"cmd": "phosphor fleet"}]},
    {"name": "VIZ", "panes": [{"cmd": "phosphor pulse"}]},
    {"name": "SH", "panes": [{"cmd": ""}]}],
    "screens": {"tablet": {"skip": ["phosphor pulse"]}, "plain": {}}}
st = kinds.tabs(sk, "tablet")
check("skip: a tab left with no panes goes", [t["name"] for t in st] == ["SYS", "SH"], st)
check("skip: a split of one becomes the pane, keeping the split's size",
      st[0]["panes"][0] == {"cmd": "phosphor adjutant", "size": 18}, st[0])
check("skip: the rest is untouched", st[0]["panes"][1] == {"cmd": "phosphor fleet"}, st[0])
check("skip: a kind without it keeps every pane", len(kinds.tabs(sk, "plain")) == 3)
e = kinds.env(prof, "eink")
check("eink's panes are told", e.get("PHOSPHOR_SCREEN") == "eink" and e.get("PHOSPHOR_THEME") == "paper"
      and "PHOSPHOR_GRAPHS" not in e and "ZELLIJ" not in e, {k: v for k, v in e.items() if "PHOS" in k})
check("a named zellij theme", "phosphor-paper {" in gen.zellij_theme("paper", "phosphor-paper"))

# 3. gen writes them (dry run: nothing touched), and the brain's deck passes its arguments
out = subprocess.run([sys.executable, PHOSPHOR, "gen", "--dry-run"], env=ENV, capture_output=True, text=True).stdout
check("gen: the phone's layout", "probe-phone.kdl" in out and "probe-eink.kdl" in out, out[-1500:])
check("gen: the eink's theme", "phosphor-paper.kdl" in out, out[-1500:])
check("gen: says what's wrong", "screens.Bad-Name" in out, out[-1500:])
check("deck hands on its arguments", 'attach "$@"' in gen.ATTACH)

# 4. the kits
check("the phone kit says phone", "deck --screen phone" in phone.script(prof))
check("screen --as eink says eink", "deck --screen eink" in phone.screen_script(prof, "eink"))
check("a plain screen says nothing", "--screen" not in phone.screen_script(prof))
r = subprocess.run([sys.executable, PHOSPHOR, "screen", "--as", "e-ink!"], env=ENV, capture_output=True, text=True)
check("a bad --as is refused", r.returncode == 1, r.stdout)

# 5. phosphor screens: any of the sessions, and which one
fake = subprocess.Popen(["zellij", "-c", "import time; time.sleep(30)", "attach", "probe-phone"],
                        executable=sys.executable)
try:
    time.sleep(0.3)
    hit = screens.is_deck_client(fake.pid, ["probe", "probe-phone"])
    miss = screens.is_deck_client(fake.pid, ["probe"])
finally:
    fake.kill()
check("screens: which session it's on", hit == "probe-phone", hit)
check("screens: not the deck's own", miss is None, miss)

# 6. --live: a real zellij makes the kind's session as attach does
if "--live" in sys.argv:
    zj = shutil.which("zellij") or os.path.expanduser("~/.local/bin/zellij")
    dump = os.path.join(HOME, "env.txt")
    lay = os.path.join(HOME, ".config/zellij/layouts")
    os.makedirs(lay, exist_ok=True)
    os.makedirs(os.path.join(HOME, ".config/zellij/themes"), exist_ok=True)
    open(os.path.join(HOME, ".config/zellij/themes/phosphor-paper.kdl"), "w").write(
        gen.zellij_theme("paper", "phosphor-paper"))
    open(os.path.join(HOME, ".config/zellij/config.kdl"), "w").write('show_startup_tips false\n')
    open(kinds.layout(prof, "eink"), "w").write(
        'layout {\n    tab name="SYS" {\n        pane command="sh" {\n'
        '            args "-c" "env > %s; sleep 60"\n        }\n    }\n}\n' % dump)
    try:
        ok = kinds.create(zj, prof, "eink")
        check("the kind's session is made", ok)
        t0 = time.time()
        while time.time() - t0 < 15 and not os.path.exists(dump):
            time.sleep(0.2)
        got = open(dump).read() if os.path.exists(dump) else ""
        check("its pane sees PHOSPHOR_SCREEN=eink", "PHOSPHOR_SCREEN=eink" in got, got[:300])
        check("its pane sees PHOSPHOR_THEME=paper", "PHOSPHOR_THEME=paper" in got)
        check("it's in zellij's list", "probe-eink" in subprocess.run(
            [zj, "list-sessions", "-n"], capture_output=True, text=True, env=ENV).stdout)
        check("restart will take it along", "probe-eink" in kinds.all_sessions(prof))
    finally:
        subprocess.run([zj, "kill-session", "probe-eink"], capture_output=True, env=ENV)
        subprocess.run([zj, "delete-session", "probe-eink", "--force"], capture_output=True, env=ENV)

shutil.rmtree(HOME, ignore_errors=True)
print("ok" if not fails else "%d failed" % fails)
sys.exit(1 if fails else 0)
