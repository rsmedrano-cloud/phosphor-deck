#!/usr/bin/env python3
"""The latest zellij release into a folder, for CI images without curl.

    python3 tests/fetch-zellij.py /usr/local/bin
"""
import io, os, platform, sys, tarfile, urllib.request

dest = sys.argv[1] if len(sys.argv) > 1 else "."
arch = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}[platform.machine()]
url = "https://github.com/zellij-org/zellij/releases/latest/download/zellij-%s-unknown-linux-musl.tar.gz" % arch
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
