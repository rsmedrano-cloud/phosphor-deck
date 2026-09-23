#!/usr/bin/env python3
"""lib/hotswap.py's judgement call: which code changes are safe to refresh
one pane for, live, instead of restarting the whole deck. No zellij here
(see tests/hotswap-live-check.py for the real-session, real-pane version,
in the "zellij" CI job) -- just the classification, against the real
lib/ directory so "is fleet.py a leaf?" is answered by the actual codebase,
not a fixture that could drift from it.

    python3 tests/hotswap-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import hotswap

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)


# 1. snapshot()/changed(): a real temp tree, not the repo's own lib/.
with tempfile.TemporaryDirectory() as td:
    lib = os.path.join(td, "lib")
    os.makedirs(lib)
    open(os.path.join(lib, "fleet.py"), "w").write("x = 1\n")
    open(os.path.join(lib, "pulse.py"), "w").write("y = 2\n")
    real_repo, real_lib = hotswap.REPO, hotswap.LIB
    hotswap.REPO, hotswap.LIB = td, lib
    try:
        before = hotswap.snapshot()
        check("snapshot sees both files", set(before) == {"lib/fleet.py", "lib/pulse.py"})
        open(os.path.join(lib, "fleet.py"), "w").write("x = 2\n")  # content changes
        after = hotswap.snapshot()
        check("changed() finds exactly the edited file", hotswap.changed(before, after) == ["lib/fleet.py"])
        check("an untouched tree changes nothing", hotswap.changed(before, before) == [])
    finally:
        hotswap.REPO, hotswap.LIB = real_repo, real_lib

# 2. module_of(): only a bare lib/*.py counts as a tool module.
check("a lib/ module", hotswap.module_of("lib/fleet.py") == "fleet")
check("share/ is never a module", hotswap.module_of("share/collect.sh") is None)
check("phosphor itself is never a module", hotswap.module_of("phosphor") is None)
check("a nested lib/ file isn't either (there shouldn't be any, but be safe)",
      hotswap.module_of("lib/sub/x.py") is None)

# 3. imported_elsewhere(): against the REAL lib/ directory.
check("ci.py is imported by review.py: not a leaf", hotswap.imported_elsewhere("ci"))
check("tabs.py is imported by several files: not a leaf", hotswap.imported_elsewhere("tabs"))
check("fleet.py is nobody else's import: a real leaf", not hotswap.imported_elsewhere("fleet"))
check("pulse.py is nobody else's import: a real leaf", not hotswap.imported_elsewhere("pulse"))

# 4. classify(): leaf-only vs. anything that triggers a real restart.
tools, reason = hotswap.classify(["lib/fleet.py"])
check("a lone leaf change: no restart, just that tool", tools == {"fleet"} and reason is None)

tools, reason = hotswap.classify(["lib/fleet.py", "lib/pulse.py"])
check("two leaf changes: both tools, no restart", tools == {"fleet", "pulse"} and reason is None)

tools, reason = hotswap.classify(["lib/gen.py"])
check("gen.py always triggers a restart (writes config.kdl/units)", reason is not None and tools == set())

tools, reason = hotswap.classify(["lib/tabs.py"])
check("a shared module (imported elsewhere) triggers a restart", reason is not None)

tools, reason = hotswap.classify(["share/collect.sh"])
check("a non-lib/ file always triggers a restart", reason is not None)

tools, reason = hotswap.classify(["lib/fleet.py", "lib/gen.py"])
check("one shared-code change outweighs any number of leaf ones", reason is not None)

tools, reason = hotswap.classify([])
check("nothing changed: nothing to do, no restart", tools == set() and reason is None)

# 5. tool_of_argv(): the real shape `phosphor run` wraps a tool in.
phosphor_run = ["/usr/bin/python3", "/x/phosphor", "run", "--name", "FLEET", "--",
                "/usr/bin/python3", "/x/phosphor", "fleet"]
check("finds the wrapped tool", hotswap.tool_of_argv(phosphor_run) == "fleet")
check("a plain shell isn't a phosphor tool", hotswap.tool_of_argv(
    ["/usr/bin/python3", "/x/phosphor", "run", "--name", "SHELL", "--", "/bin/bash", "-l"]) is None)
check("an ssh pane isn't a phosphor tool either", hotswap.tool_of_argv(
    ["/usr/bin/python3", "/x/phosphor", "run", "--reconnect", "--", "ssh", "-t", "some-remote"]) is None)
check("no argv at all", hotswap.tool_of_argv(None) is None)
check("no -- separator", hotswap.tool_of_argv(["btop"]) is None)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
