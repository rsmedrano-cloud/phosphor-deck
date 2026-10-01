"""phosphor face - turns an image (or animation) into a face for the adjutant.

Uses ImageMagick: each frame is shrunk to a tiny grayscale grid and mapped
to characters by density. The result is a JSON of frames the adjutant plays.

    phosphor face head.webp --name adjutant --w 24 --h 13

With no IMAGE, on a terminal, it asks which (folders from here, ~ and
~/fleet one key away) and uses the defaults for the rest.
"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

HOME  = os.path.expanduser("~")
FACES = os.path.join(deckconf.data_dir(), "faces")          # like the adjutant reads it
RAMP  = " .·:░▒▓█"                                          # empty to solid
HALF  = {(0,0): " ", (0,1): "▄", (1,0): "▀", (1,1): "█"}

def have(b):
    from shutil import which
    return which(b)

def frame_count(src):
    try:
        out = subprocess.run(["identify", src], capture_output=True, text=True, timeout=60)
        return max(1, len(out.stdout.strip().splitlines()))
    except Exception:
        import dlog
        dlog.event("FACE", "frame-count-failed")   # never the path: it's the image the caller gave
        return 1

def grid(src, idx, w, h, gamma, crop=None, half=False, thr=0.45, mode="thr"):
    """One frame -> a list of strings w wide.

    half=True samples twice the rows and joins them with half blocks: it
    doubles the vertical resolution, which is where it hurts most because
    terminal cells are twice as tall as they are wide."""
    rows_px = h * 2 if half else h
    # -coalesce first: an optimized GIF stores only the changed rectangle per
    # frame, so frame N on its own is a partial picture. (-clone N then
    # dropping everything before it keeps just that complete frame.)
    pre = ["convert", src, "-coalesce", "-clone", str(idx), "-delete", "0--2", "+repage"]
    if crop:
        pre += ["-gravity", "center", "-crop", crop, "+repage"]
    # -normalize stretches the histogram: source images tend to be dark and
    # the density ramp would otherwise sit in the low tones.
    post = []
    if mode == "dither":
        # error diffusion keeps a sense of tone at tiny resolutions
        post = ["-monochrome"]
    elif mode == "edge":
        # at low resolution an outline reads better than a blob
        post = ["-canny", "0x1+5%+20%"]
    cmd = pre + ["-resize", "%dx%d!" % (w, rows_px),
                 "-colorspace", "gray", "-normalize"] + post + ["-depth", "8", "txt:-"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    px = {}
    for line in out.splitlines():
        m = re.match(r"(\d+),(\d+):\s*\((\d+)", line)
        if m:
            px[(int(m.group(1)), int(m.group(2)))] = int(m.group(3))
    if not px: return []
    val = lambda x, y: (px.get((x, y), 0) / 255.0) ** gamma
    rows = []
    if half:
        for y in range(h):
            s = ""
            for x in range(w):
                t = 1 if val(x, y * 2) > thr else 0
                b = 1 if val(x, y * 2 + 1) > thr else 0
                s += HALF[(t, b)]
            rows.append(s.rstrip() or " ")
    else:
        for y in range(h):
            s = ""
            for x in range(w):
                v = val(x, y)
                s += RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))]
            rows.append(s.rstrip() or " ")
    return rows

# A bitmap face: the picture kept as a small grid of tones, drawn at whatever
# size the pane has (lib/facebmp.py), instead of one fixed grid of characters.
# Tone digits 0-f are brightness; g-n mark an accent (a light on the helmet)
# with its own brightness, which the adjutant pulses and turns red on alert.
TONES, ACCENTS = "0123456789abcdef", "ghijklmn"

def _grid(cmd):
    """convert ... txt:- -> {(x, y): (r, g, b)}."""
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    px = {}
    for line in out.splitlines():
        m = re.match(r"(\d+),(\d+):\s*\((\d+),(\d+),(\d+)", line)
        if m:
            px[(int(m.group(1)), int(m.group(2)))] = tuple(int(m.group(i)) for i in (3, 4, 5))
    return px

def bitmap(src, px_w, px_h, crop=None):
    """One image -> a list of px_h strings px_w wide, in TONES/ACCENTS."""
    pre = ["convert", src, "-coalesce", "-clone", "0", "-delete", "0--2", "+repage"]
    if crop:
        pre += ["-crop", crop, "+repage"]
    size = ["-resize", "%dx%d!" % (px_w, px_h), "-depth", "8", "txt:-"]
    px = _grid(pre + size)
    if not px: return []
    # The lights are thin dithered strokes: shrunk with everything else they
    # wash out. So they are found in the full-size picture (warm and bright)
    # and shrunk on their own, as coverage.
    warm = "(r>0.35 && r>g+0.03 && r-b>0.14) ? 1 : 0"      # teal has g > r, amber the reverse
    # dilated first: a one-pixel stroke would vanish at this size
    cov = _grid(pre + ["-colorspace", "sRGB", "-fx", warm, "-morphology", "Dilate", "Disk:5",
                       "-colorspace", "Gray"] + size)
    lum = {k: 0.3 * r + 0.59 * g + 0.11 * b for k, (r, g, b) in px.items()}
    vals = sorted(lum.values())
    lo, hi = vals[len(vals) // 50], vals[len(vals) * 99 // 100]    # the picture is dark
    rows = []
    for y in range(px_h):
        s = ""
        for x in range(px_w):
            c = cov.get((x, y), (0, 0, 0))[0] / 255.0
            if c > 0.15:
                s += ACCENTS[min(7, int(c * 8))]
            else:
                t = min(1.0, max(0.0, (lum[(x, y)] - lo) / max(1.0, hi - lo))) ** 0.85
                s += TONES[min(15, int(t * 16))]
        rows.append(s)
    return rows

IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

def run(argv):
    import form
    if form.wanted(argv):
        picked = form.file("phosphor face -- which image?", exts=IMAGES)
        form.leave()
        if not picked:
            return 0
        argv = [picked]
    if not argv:
        print("usage: phosphor face IMAGE [--name N] [--w 24] [--h 13]")
        print("           [--max-frames 24] [--gamma G] [--crop GEOM] [--half] [--thr 0.45]")
        print("           [--mode thr|dither|edge]")
        print("       phosphor face IMAGE --bitmap [--closed IMAGE] [--px 96] [--crop WxH+X+Y]")
        return 1
    src = argv[0]
    if not os.path.exists(src):
        print("no such file: %s" % src); return 1
    if not have("convert"):
        print("ImageMagick (convert) is missing"); return 1

    def opt(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default
    name  = opt("--name", os.path.splitext(os.path.basename(src))[0])
    w     = int(opt("--w", 24)); h = int(opt("--h", 13))
    cap   = int(opt("--max-frames", 24))
    gamma = float(opt("--gamma", 0.85))
    crop  = opt("--crop", None)
    half  = "--half" in argv
    thr   = float(opt("--thr", 0.45))
    mode  = opt("--mode", "thr")

    if "--bitmap" in argv:
        # phosphor face open.png --bitmap [--closed shut.png] [--px 96] [--crop WxH+X+Y]
        pw = int(opt("--px", 96))
        ph = pw
        if crop:
            cw, ch = (int(v) for v in re.match(r"(\d+)x(\d+)", crop).groups())
            ph = max(1, round(pw * ch / cw))
        frames = {"open": bitmap(src, pw, ph, crop)}
        closed = opt("--closed", None)
        if closed:
            frames["closed"] = bitmap(closed, pw, ph, crop)
        if not frames["open"]:
            print(row(BAD, "no pixels", "convert returned nothing")); return 1
        os.makedirs(FACES, exist_ok=True)
        dest = os.path.join(FACES, name + ".json")
        json.dump({"v": 2, "w": pw, "h": ph, "bitmap": frames}, open(dest, "w"))
        print(row(OK, "bitmap", "%dx%d, %s" % (pw, ph, " + ".join(frames))))
        print(row(OK, "written", dest))
        print("  " + DIM + "use it with: phosphor adjutant --face " + name + RST)
        return 0

    total = frame_count(src)
    step  = max(1, total // cap)
    picks = list(range(0, total, step))[:cap]
    print()
    print(BLOOM + "  phosphor face" + RST)
    print(row(OK, "source", "%s  (%d frames)" % (os.path.basename(src), total)))
    print(row(OK, "grid", "%dx%d characters%s" % (w, h, "  (half blocks)" if half else "")))
    if crop: print(row(OK, "crop", crop))
    print(row(OK, "mode", mode))
    print(row(OK, "extracting", "%d frames (1 in %d)" % (len(picks), step)))

    frames = []
    for n, i in enumerate(picks):
        g = grid(src, i, w, h, gamma, crop, half, thr, mode)
        if g: frames.append(g)
        sys.stdout.write("\r  " + DIM + "…%d/%d" % (n + 1, len(picks)) + RST)
        sys.stdout.flush()
    print("\r" + " " * 24 + "\r", end="")
    if not frames:
        print(row(BAD, "no frames", "convert returned no pixels")); return 1

    os.makedirs(FACES, exist_ok=True)
    dest = os.path.join(FACES, name + ".json")
    json.dump({"w": w, "h": h, "frames": frames}, open(dest, "w"))
    print(row(OK, "written", dest))
    print()
    for line in frames[0]:
        print("  " + PH + line + RST)
    print()
    print("  " + DIM + "use it with: phosphor adjutant --face " + name + RST)
    print()
    return 0
