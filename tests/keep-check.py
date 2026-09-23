#!/usr/bin/env python3
"""Reading a live tab back into profile shape.

    python3 tests/keep-check.py

A dumped layout (tests/fixtures/dump-layout.kdl) becomes the TOML `phosphor
keep` writes: the tab bar dropped, `phosphor run` unwrapped into the command
it watches, splits and sizes kept, and what gen expands (@work, @hosts,
@mount_root) folded back so a kept tab doesn't freeze today's addresses.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import keep

# absolute, and with the addresses gen would expand: the point of the test is
# that a kept tab keeps the tokens, not what they happened to resolve to
PROFILE = {"deck": {"mount_root": "/home/someone/fleet"},
           "hosts": [{"name": "brain", "role": "brain", "local": True, "ip": "10.0.0.1"},
                     {"name": "workbox", "role": "work", "ssh": "workbox", "ip": "10.0.0.2", "mount": "/"}]}

WANT = {
    "WORK": '''[[tabs]]
name  = "WORK"
panes = [
  { ssh = "@work", reconnect = true },
]
''',
    "MIX": '''[[tabs]]
name  = "MIX"
split = "cols"
panes = [
  { cmd = "yazi", args = ["@mount_root"], needs_size = true, size = "70%" },
  { split = "rows", panes = [{ cmd = "gping", args = ["@hosts"], alt = true, size = 12 }, { cwd = "~/projects/api" }], size = "30%" },
]
''',
}

def main():
    text = open(os.path.join(HERE, "fixtures", "dump-layout.kdl")).read()
    layout = keep.parse(text)
    keep.HOME = "/home/someone"
    ctx = keep.context(PROFILE, cwd="/home/someone")
    bad = 0
    for name, want in WANT.items():
        got = keep.block(*keep.tab_specs(layout, name, ctx))
        if got.strip() == want.strip():
            print("  ok    %s" % name)
        else:
            bad += 1
            print("  FAIL  %s\n--- got:\n%s--- want:\n%s" % (name, got, want))
    print("\n%s" % ("PASS: a live tab reads back into the profile" if not bad else "FAIL: %d" % bad))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
