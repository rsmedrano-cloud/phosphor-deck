#!/usr/bin/env python3
"""lib/hotswap.py against a real zellij session: finding a real pane
running a real `phosphor` tool, and swapping it in place for a fresh
process without touching anything else. Never the live deck -- a
throwaway session (tests/zjprobe.py), client attached in a pty.

    python3 tests/hotswap-live-check.py

Needs zellij; without it, it says so and passes (same as tests/edit-check.py,
which this is the same spirit as -- lib/edit.py's own Alt-r "swap the
program" uses the exact same zellij primitive this module reuses).
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import zjprobe
import hotswap

PROFILE = '''
[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "PULSE"
panes = [ { cmd = "phosphor", args = ["pulse"] } ]

[[tabs]]
name  = "SH"
panes = [ { cmd = "sleep", args = ["601"] } ]
'''

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)


def main():
    if not zjprobe.zellij():
        print("no zellij here: skipped"); return 0
    with zjprobe.Probe(PROFILE, session="probe") as z:
        # The throwaway session's socket lives in the probe's own isolated
        # ZELLIJ_SOCKET_DIR, not the default location -- hotswap's own
        # `zellij -s probe ...` calls need that in their environment to find
        # it (in production there's no override, so this only matters here).
        old_env = os.environ.get("ZELLIJ_SOCKET_DIR")
        os.environ["ZELLIJ_SOCKET_DIR"] = z.env["ZELLIJ_SOCKET_DIR"]
        try:
            # zellij's own view of the panes needs a moment to settle after
            # attach, and argv_of() reads /proc, which needs the outer
            # `phosphor run` process to have actually exec'd its child --
            # poll for it instead of guessing a fixed sleep.
            z.wait(lambda: len(z.tabs()) == 2, 10)
            panes, end = [], time.time() + 10
            while time.time() < end:
                panes = hotswap.live_panes("probe")
                if len(panes) == 2 and any(hotswap.tool_of_argv(a) == "pulse" for _, a in panes):
                    break
                time.sleep(0.3)

            need("finds both real panes", len(panes) == 2)
            pulse = [(pid, argv) for pid, argv in panes if hotswap.tool_of_argv(argv) == "pulse"]
            need("identifies the phosphor-pulse pane by its real argv", len(pulse) == 1)
            if pulse:
                pane_id, argv = pulse[0]
                others = [(pid, argv) for pid, argv in panes if hotswap.tool_of_argv(argv) != "pulse"]
                need("the shell pane is never mistaken for a phosphor tool",
                     others and hotswap.tool_of_argv(others[0][1]) is None)

                old_procs = hotswap.pane_procs("probe", pane_id)
                need("the pane has real processes before swapping", bool(old_procs))

                hotswap.swap("probe", pane_id, argv)
                z.pump(1.0)

                # zellij's own "--in-place" gives the fresh content a NEW pane
                # id (it replaces what's shown, not the id) -- poll for a
                # phosphor-pulse pane to reappear at all, not the old id.
                new_panes, end = [], time.time() + 10
                while time.time() < end:
                    new_panes = hotswap.live_panes("probe")
                    if len(new_panes) == 2 and any(hotswap.tool_of_argv(a) == "pulse" for _, a in new_panes):
                        break
                    time.sleep(0.3)

                need("every old process is gone after the swap",
                     all(not os.path.exists("/proc/%d" % p) for p in old_procs))
                need("the tab is still there, same two tabs as before", len(z.tabs()) == 2)

                new_pulse = [(pid, a) for pid, a in new_panes if hotswap.tool_of_argv(a) == "pulse"]
                need("phosphor pulse is running again, exactly one pane",
                     len(new_pulse) == 1)
                need("total live panes is still 2 -- nothing left duplicated",
                     len(new_panes) == 2)
                if new_pulse:
                    new_procs = hotswap.pane_procs("probe", new_pulse[0][0])
                    need("its processes are new pids, not the ones killed",
                         bool(new_procs) and not (set(new_procs) & set(old_procs)))

                # The untouched tab (SH) never noticed any of this.
                shell_panes = [(pid, a) for pid, a in hotswap.live_panes("probe")
                              if hotswap.tool_of_argv(a) is None]
                need("the other tab's pane was never touched", len(shell_panes) == 1)
        finally:
            if old_env is None:
                os.environ.pop("ZELLIJ_SOCKET_DIR", None)
            else:
                os.environ["ZELLIJ_SOCKET_DIR"] = old_env

    if fails:
        print("FAILED:\n  " + "\n  ".join(fails))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
