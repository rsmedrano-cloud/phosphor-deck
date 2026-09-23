#!/usr/bin/env python3
"""Read our own QR codes back: what a scanner does, minus the camera.

    python3 tests/qr-check.py

For strings of every length the deck can need: rebuild the format info,
undo the mask, read the modules in the zigzag order, parse the byte-mode
segment, and check the error-correction remainder is zero.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import qr

def read_format(m):
    n = len(m)
    bits = [m[8][i] for i in range(6)] + [m[8][7], m[8][8], m[7][8]] + [m[14 - i][8] for i in range(9, 15)]
    f = 0
    for i, b in enumerate(bits):
        f |= b << i
    f ^= 0x5412
    ec, mask = (f >> 13) & 0b11, (f >> 10) & 0b111
    return ec, mask

def read_codewords(m, mask):
    n, out, bits = len(m), [], []
    _, fn = qr.frame((n - 17) // 4)
    up, col = True, n - 1
    while col > 0:
        if col == 6:
            col -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for c in (col, col - 1):
                if not fn[r][c]:
                    v = m[r][c] ^ (1 if qr.MASKS[mask](r, c) else 0)
                    bits.append(v)
        up, col = not up, col - 2
    for i in range(0, len(bits) - 7, 8):
        out.append(int("".join(str(b) for b in bits[i:i + 8]), 2))
    return out

def decode(m):
    ec, mask = read_format(m)
    assert ec == 0b01, "error correction level should be L, got %r" % ec
    cw = read_codewords(m, mask)
    ver = (len(m) - 17) // 4
    total, ecn, _ = qr.SPEC[ver]
    assert len(cw) == total, "%d codewords, expected %d" % (len(cw), total)
    # a scanner divides the whole thing by the generator: the rest must be 0
    assert qr.ec_codewords(cw[:total - ecn], ecn) == cw[total - ecn:], "error correction bytes don't match"
    bits = "".join(format(c, "08b") for c in cw)
    assert bits[:4] == "0100", "not byte mode: %s" % bits[:4]
    ln = int(bits[4:12], 2)
    data = bytes(int(bits[12 + i * 8:20 + i * 8], 2) for i in range(ln))
    return data.decode("utf-8")

def main():
    cases = ["x", "deck", "ssh you@brain '~/.local/bin/phosphor phone' | sh",
             "a" * 17, "b" * 32, "c" * 53, "d" * 78, "e" * 106, "ñ áé · ünïcödé"]
    bad = 0
    for text in cases:
        m = qr.encode(text)
        if m is None:
            print("  FAIL  doesn't fit: %r" % text[:30]); bad += 1; continue
        try:
            back = decode(m)
        except AssertionError as e:
            print("  FAIL  %r: %s" % (text[:30], e)); bad += 1; continue
        ok = back == text
        bad += not ok
        print("  %s  v%d %2dx%2d  %r" % ("ok  " if ok else "FAIL", (len(m) - 17) // 4,
                                         len(m), len(m), text[:30]))
    print("\n%s" % ("PASS: every code reads back" if not bad else "FAIL: %d" % bad))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
