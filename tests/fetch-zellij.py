#!/usr/bin/env python3
"""The zellij Phosphor is tested with (share/versions.json) into a folder,
for CI images without curl. --latest takes the newest release instead: CI's
zellij-latest job, the early warning for a release that changes something.

    python3 tests/fetch-zellij.py /usr/local/bin
    python3 tests/fetch-zellij.py --latest /usr/local/bin
"""
import io, json, os, platform, sys, tarfile, urllib.request

args = [a for a in sys.argv[1:] if a != "--latest"]
dest = args[0] if args else "."
arch = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}[platform.machine()]
if "--latest" in sys.argv:
    rel = "latest/download"
else:
    pinned = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "share", "versions.json")
    rel = "download/v%s" % json.load(open(pinned))["zellij"].lstrip("v")
url = "https://github.com/zellij-org/zellij/releases/%s/zellij-%s-unknown-linux-musl.tar.gz" % (rel, arch)
for attempt in range(3):                      # GitHub sometimes answers 5xx
    try:
        data = urllib.request.urlopen(url, timeout=60).read(); break
    except Exception as e:
        if attempt == 2: sys.exit("couldn't download zellij: %s" % e)
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    member = next(m for m in t.getmembers() if os.path.basename(m.name) == "zellij")
    out = os.path.join(dest, "zellij")
    with open(out, "wb") as f:
        f.write(t.extractfile(member).read())
os.chmod(out, 0o755)
print(out)
