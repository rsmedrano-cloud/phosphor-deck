"""A QR code drawn in the terminal, in pure Python.

Only what the deck needs: byte mode, error correction L, versions 1-5 (up
to 106 characters), which is one error-correction block and so needs no
interleaving. No dependency and no root: qrencode isn't installed by
default anywhere, and the deck never asks for sudo.
"""

# version: (total codewords, error-correction codewords, alignment centre)
SPEC = {1: (26, 7, 0), 2: (44, 10, 18), 3: (70, 15, 22), 4: (100, 20, 26), 5: (134, 26, 30)}

EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i], LOG[_x] = _x, _i
    _x = (_x << 1) ^ 0x11D if _x & 0x80 else _x << 1
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]

def mul(a, b):
    return 0 if not a or not b else EXP[LOG[a] + LOG[b]]

def generator(n):
    g = [1]
    for i in range(n):
        g = [(g + [0])[j] ^ mul((([0] + g)[j]), EXP[i]) for j in range(len(g) + 1)]
    return g

def ec_codewords(data, n):
    """The remainder of the data polynomial divided by the generator."""
    g, rem = generator(n), list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j, gj in enumerate(g):
                rem[i + j] ^= mul(gj, c)
    return rem[len(data):]

def version_for(text):
    n = len(text.encode("utf-8"))
    for v in sorted(SPEC):
        total, ec, _ = SPEC[v]
        if (total - ec) * 8 - 12 >= n * 8:
            return v
    return None

def codewords(text, ver):
    total, ec, _ = SPEC[ver]
    cap, b = total - ec, text.encode("utf-8")
    bits = "0100" + format(len(b), "08b") + "".join(format(x, "08b") for x in b)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    while len(cw) < cap:
        cw.append(0xEC if (cap - len(cw)) % 2 else 0x11)
    return cw + ec_codewords(cw, ec)

def frame(ver):
    """The function patterns, and which modules they occupy."""
    n = ver * 4 + 17
    m = [[0] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]
    def box(r0, c0, h, w, fill):
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                if 0 <= r < n and 0 <= c < n:
                    m[r][c], fn[r][c] = fill(r - r0, c - c0), True
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):          # finders
        box(r0, c0, 7, 7, lambda r, c: 0 if (r in (1, 5) and 0 < c < 6)
            or (c in (1, 5) and 0 < r < 6) else 1)
    box(7, 0, 1, 8, lambda r, c: 0); box(0, 7, 8, 1, lambda r, c: 0)   # separators
    box(7, n - 8, 1, 8, lambda r, c: 0); box(0, n - 8, 8, 1, lambda r, c: 0)
    box(n - 8, 0, 1, 8, lambda r, c: 0); box(n - 8, 7, 8, 1, lambda r, c: 0)
    for i in range(8, n - 8):                                 # timing
        m[6][i] = m[i][6] = (i + 1) % 2
        fn[6][i] = fn[i][6] = True
    a = SPEC[ver][2]
    if a:
        box(a - 2, a - 2, 5, 5, lambda r, c: 1 if r in (0, 4) or c in (0, 4) or (r, c) == (2, 2) else 0)
    m[n - 8][8], fn[n - 8][8] = 1, True                       # the dark module
    for i in range(9):                                        # format areas
        fn[8][i] = fn[i][8] = True
    for i in range(8):                                        # and their copy
        fn[8][n - 1 - i] = fn[n - 1 - i][8] = True
    return m, fn

def place(m, fn, bits):
    n, i, up, col = len(m), 0, True, len(m) - 1
    while col > 0:
        if col == 6:
            col -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for c in (col, col - 1):
                if not fn[r][c]:
                    m[r][c] = int(bits[i]) if i < len(bits) else 0
                    i += 1
        up, col = not up, col - 2

MASKS = [lambda r, c: (r + c) % 2 == 0,
         lambda r, c: r % 2 == 0,
         lambda r, c: c % 3 == 0,
         lambda r, c: (r + c) % 3 == 0,
         lambda r, c: (r // 2 + c // 3) % 2 == 0,
         lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
         lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
         lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]

def format_info(m, fn, mask):
    n = len(m)
    f = (0b01 << 3) | mask                     # error correction L
    v = f << 10
    while v.bit_length() > 10:
        v ^= 0x537 << (v.bit_length() - 11)
    f = ((f << 10) | v) ^ 0x5412
    bits = [(f >> i) & 1 for i in range(15)]
    for i in range(6):
        m[8][i] = bits[i]
    m[8][7], m[8][8], m[7][8] = bits[6], bits[7], bits[8]
    for i in range(9, 15):
        m[14 - i][8] = bits[i]
    for i in range(8):
        m[n - 1 - i][8] = bits[i]
    for i in range(8, 15):
        m[8][n - 15 + i] = bits[i]
    m[n - 8][8] = 1

def penalty(m):
    n, p = len(m), 0
    lines = [[m[r][c] for c in range(n)] for r in range(n)]
    lines += [[m[r][c] for r in range(n)] for c in range(n)]
    for line in lines:
        run, prev = 1, line[0]
        for v in line[1:]:
            run = run + 1 if v == prev else 1
            if run == 5: p += 3
            elif run > 5: p += 1
            prev = v
        s = "".join(str(v) for v in line)
        for pat in ("10111010000", "00001011101"):
            p += 40 * s.count(pat)
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(sum(row) for row in m) * 100 // (n * n)
    p += 10 * (abs(dark - 50) // 5)
    return p

def encode(text):
    """The module grid (1 = dark), or None if the text doesn't fit."""
    ver = version_for(text)
    if not ver:
        return None
    bits = "".join(format(c, "08b") for c in codewords(text, ver))
    best = None
    for mask in range(8):
        m, fn = frame(ver)
        place(m, fn, bits)
        for r in range(len(m)):
            for c in range(len(m)):
                if not fn[r][c] and MASKS[mask](r, c):
                    m[r][c] ^= 1
        format_info(m, fn, mask)
        score = penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]

def render(m, quiet=4):
    """Two module rows per text row, so the code comes out square-ish."""
    n = len(m) + quiet * 2
    grid = [[0] * n for _ in range(n)]
    for r, row in enumerate(m):
        for c, v in enumerate(row):
            grid[r + quiet][c + quiet] = v
    WHITE, BLACK = "\x1b[48;5;15m\x1b[38;5;15m", "\x1b[48;5;0m\x1b[38;5;0m"
    out = []
    for r in range(0, n, 2):
        line = ""
        for c in range(n):
            top = grid[r][c]
            bot = grid[r + 1][c] if r + 1 < n else 0
            line += ("\x1b[48;5;15m" if not bot else "\x1b[48;5;0m")
            line += ("\x1b[38;5;0m" if top else "\x1b[38;5;15m") + "▀"
        out.append(line + "\x1b[0m")
    return out

def width(text):
    """How many columns render() needs, or 0 if the text doesn't fit."""
    ver = version_for(text)
    return (ver * 4 + 17 + 8) if ver else 0
