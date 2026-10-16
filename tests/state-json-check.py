#!/usr/bin/env python3
"""Every card that shows a state finds it in its command's real --json.

    python3 tests/state-json-check.py

doors-check reads share/commands.json; card-check fakes the commands. This
runs them: each sensor's and toggle's `from` arguments, through the real
dispatcher, in a throwaway HOME with a small profile that has no [ci],
[prometheus] or signed-in assistants (so nothing asks the network), and
checks the answer is one JSON object, the card's dotted `state` is in it,
and its `why` is null or a line. Commands that read the deck's own session
or the fleet over ssh are left to their own checks.
"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli

SKIP = {"fleet", "screens", "mem", "security", "services", "tunnel", "workspace", "version", "glance", "stats"}
HOME = tempfile.mkdtemp()
PROFILE = os.path.join(HOME, "deck.toml")
with open(PROFILE, "w") as f:
    f.write('[deck]\nname = "probe"\n\n[[hosts]]\nname = "db-box"\nlocal = true\nrole = "brain"\n\n'
            '[push]\nenabled = true\n')
env = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
env.update(HOME=HOME, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(HOME, "data"),
           PHOSPHOR_CACHE=os.path.join(HOME, "cache"), XDG_CONFIG_HOME=os.path.join(HOME, ".config"))

fails, ran = [], []
for name, e in sorted(cli.entries().items()):
    c = e.get("card") or {}
    if "state" not in c or name in SKIP:
        continue
    argv = c.get("from", ["--json"])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), name] + argv, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    ran.append(name)
    try:
        v = top = json.loads(r.stdout)
    except ValueError:
        fails.append("phosphor %s %s: not one JSON object: %r" % (name, " ".join(argv), (r.stdout + r.stderr)[:200]))
        continue
    try:
        for k in c["state"].split("."):
            v = v[k]
    except (KeyError, TypeError, IndexError):
        fails.append("phosphor %s %s: no `%s` in its answer (keys: %s)" % (name, " ".join(argv), c["state"],
                                                                         ", ".join(top) if isinstance(top, dict) else "-"))
        continue
    if "why" in top and not (top["why"] is None or isinstance(top["why"], str) and top["why"].strip()):
        fails.append("phosphor %s: `why` is null or a line, not %r" % (name, top["why"]))

push = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "push", "status", "--json"],
                                 env=env, capture_output=True, text=True, timeout=60).stdout)
if not (push["enabled"] and push["topic"] is False and push["why"]):
    fails.append("push status --json: on with no topic is a why")
if not {"web", "push", "tts", "solaros", "trace", "ci", "prom", "usage"} <= set(ran):
    fails.append("ran only " + " ".join(ran))

if fails:
    print("state-json-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("state-json-check ok (%d cards: %s)" % (len(ran), " ".join(ran)))
