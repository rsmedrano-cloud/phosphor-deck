#!/usr/bin/env python3
"""The store and piper install the build for this machine: x86_64 or aarch64.

    python3 tests/store-arch-check.py

Every store.json entry's matcher is resolved for both arches against the
asset names its upstream really published (tests/fixtures/store-assets.json),
exactly one asset each; a package holding every arch (broot) gives ours;
piper's download is linux_aarch64 on aarch64. Nothing leaves the machine:
urlopen is faked.
"""
import io, json, os, re, sys, tempfile, urllib.request, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import store, tts

fails = []
def need(what, ok):
    if not ok: fails.append(what)

ARCHES = ("x86_64", "aarch64")
NONE = {"aarch64": {"jless", "dog"}}          # upstream ships no aarch64 build
OTHER = {"x86_64": ("aarch64", "arm64"), "aarch64": ("x86_64", "amd64")}

# 1. every entry, both arches, against the real asset names
catalog = json.load(open(os.path.join(ROOT, "share", "store.json")))
assets = json.load(open(os.path.join(ROOT, "tests", "fixtures", "store-assets.json")))
for app in catalog:
    if not app.get("r"): continue
    names = assets.get(app["r"])
    need("%s: in the fixture" % app["n"], names is not None)
    if names is None: continue
    for a in ARCHES:
        if app["n"] in NONE.get(a, ()):
            need("%s: no %s matcher" % (app["n"], a), store.matcher(app, a) is None)
            continue
        hits = [n for n in names if re.search(store.matcher(app, a), n)]
        need("%s/%s: exactly one asset, got %s" % (app["n"], a, hits), len(hits) == 1)
        got = store.pick(app, names, a) or ""
        if not store.inside(app, a):            # one package for every arch carries no arch name
            need("%s/%s: %s isn't another arch's" % (app["n"], a, got),
                 not any(o in got for o in OTHER[a]))
            need("%s/%s: %s is linux, not a phone or a mac" % (app["n"], a, got),
                 not any(o in got for o in ("android", "darwin", "apple", "macos", ".deb", ".rpm", ".apk")))

for m, want in (("AMD64", "x86_64"), ("x86_64", "x86_64"), ("arm64", "aarch64"), ("aarch64", "aarch64")):
    store.platform.machine = lambda m=m: m
    need("arch(): %s is %s" % (m, want), store.arch() == want)
need("an old string matcher is x86_64 only",
     store.matcher({"m": "x"}, "x86_64") == "x" and store.matcher({"m": "x"}, "aarch64") is None)

# 2. a package with every arch inside (broot): install copies ours, not the first one walked
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    for d in ("aarch64-apple-darwin", "aarch64-unknown-linux-musl", "x86_64-linux-android",
              "x86_64-unknown-linux-musl"):
        z.writestr(d + "/broot", d + "\n" + "x" * 200000)
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
broot = next(a for a in catalog if a["n"] == "broot")
with tempfile.TemporaryDirectory() as td:
    store.BIN = td
    store.urllib.request.urlopen = lambda req, timeout=0: Resp(buf.getvalue())
    store.fetch_asset = lambda app: ("https://example.invalid/broot.zip", "broot_1.0.zip", "v1.0")
    for a in ARCHES:
        store.arch = lambda a=a: a
        store.install(broot, lambda s: None)
        first = open(os.path.join(td, "broot")).readline().strip()
        need("broot on %s installs %s-unknown-linux-musl, got %s" % (a, a, first),
             first == a + "-unknown-linux-musl")

def quiet(f):
    out, old = io.StringIO(), sys.stdout
    sys.stdout = out
    try: return f(), out.getvalue()
    finally: sys.stdout = old

# 3. piper's download on aarch64 is linux_aarch64; a missing arch says which
rel = {"assets": [{"name": n, "browser_download_url": "https://example.invalid/" + n}
                  for n in assets["rhasspy/piper"]]}
urllib.request.urlopen = lambda req, timeout=0: Resp(json.dumps(rel).encode())
got = []
tts.download_file_with_progress = lambda url, dest: got.append(url) or False
for a in ARCHES:
    store.arch = lambda a=a: a
    del got[:]
    quiet(tts.install_piper)
    need("piper on %s downloads linux_%s, got %s" % (a, a, got), len(got) == 1 and got[0].endswith("piper_linux_%s.tar.gz" % a))
store.arch = lambda: "riscv64"
code, said = quiet(tts.install_piper)
need("piper on riscv64 fails and names the arch", code == 1 and "riscv64" in said)

if fails:
    print("store-arch-check: %d failed" % len(fails))
    for f in fails: print("  FAIL", f)
    sys.exit(1)
print("store-arch-check: ok")
