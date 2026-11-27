#!/usr/bin/env python3
"""Pixel-art scenes for a mega tree (or any tall pixel grid), timed to the song.

The scenes are drawn on a 16 x 75 tree buffer (column = strand left to right, row 0 = the
top of the tree) and, if you ask for another --size, resampled to it. Black = off. Each
scene writes a GIF made to play from --start to --end in the song; put it in the plan as
a "picture" cue over exactly that span (one effect, never split, so it doesn't restart).

    python lor_pixelart.py scenes                                   # list them
    python lor_pixelart.py render bell --start 164.9 --end 172.1 --analysis song.analysis.json --out bell.gif
    python lor_pixelart.py render flames --start 151 --end 165 --analysis song.analysis.json --hits 158.5,158.95,160.3 --out flames.gif
    python lor_pixelart.py sheet bell.gif --out bell_sheet.png      # frames sampled by time, to look at

See references/pixel_art.md for how to design new scenes and why these ones read well.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 16, 75                     # the drawing buffer (a 16-strand Tree 180 with 75 lights per strand)
OUT_SIZE = (W, H)                 # --size resamples to this
FPS = 20
rng = np.random.default_rng(7)
WHITE, ICE, GOLD, RED, GREEN = (255, 255, 255), (170, 210, 255), (255, 185, 30), (255, 20, 10), (0, 200, 40)
STEAM = (235, 240, 250)
CHOC_DARK, CHOC, CHOC_LIGHT = np.array([150, 55, 5]), np.array([215, 95, 15]), np.array([255, 150, 50])
MUG = np.array([255, 25, 25])
FOAM = np.array([255, 235, 190])

BEATS: list = []                  # filled from the song analysis
BARS: list = []
HITS: list = []                   # --hits: chugs, "hot hot" hits, firework bursts...
SLOW: list = []                   # steam_stop: chug times getting further apart; the last one is the stop


def save(frames, path, ms):
    imgs = [Image.fromarray(np.clip(f, 0, 255).astype(np.uint8), "RGB") for f in frames]
    if OUT_SIZE != (W, H):
        imgs = [im.resize(OUT_SIZE, Image.BILINEAR) for im in imgs]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=ms, loop=0, disposal=1, optimize=False)
    print(f"{path}: {len(imgs)} frames x {ms} ms = {len(imgs) * ms / 1000:.1f}s at {OUT_SIZE[0]}x{OUT_SIZE[1]}")


def add(img, x, y, rgb, a=1.0):
    """Light one pixel (brightest wins), ignoring anything off the buffer."""
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < W and 0 <= yi < H:
        img[yi, xi] = np.maximum(img[yi, xi], np.array(rgb) * a)


def eighths():
    return [BEATS[i] + (BEATS[i + 1] - BEATS[i]) * j / 2 for i in range(len(BEATS) - 1) for j in range(2)]


def chugs():
    """Train chugs for the boiler: --hits if given, else every eighth note."""
    return HITS or eighths()


def slowdown(start, end, first=0.11, grow=1.13):
    """Steps that keep getting further apart until about 85% of the span: a train coming to a stop."""
    t, gap, out = start, first, []
    while t < start + (end - start) * 0.85:
        out.append(round(t, 3))
        t += gap
        gap *= grow
    return out


def cup_frame(t, level, img=None, marsh=False):
    """level 0..1 = how full. Wavy surface, rising bubbles, steam, optional bobbing marshmallows."""
    img = np.zeros((H, W, 3)) if img is None else img
    base = H - 1
    full_top = 12                      # liquid can rise to row 12 (cup rim at row 10)
    surf = base - level * (base - full_top)
    # red mug outline on the outermost strands + base rows
    for y in range(10, H):
        add(img, 0, y, MUG, 0.85)
        add(img, W - 1, y, MUG, 0.85)
    for x in range(W):
        add(img, x, H - 1, MUG, 0.85)
    for x in range(1, W - 1):
        s = surf + 1.4 * math.sin(x * 0.75 + t * 5.0) + 0.8 * math.sin(x * 1.9 - t * 7.3)   # sloshing
        for y in range(H - 2, -1, -1):
            if y < s:
                break
            depth = (y - s) / max(1, (H - 2 - s))
            c = CHOC_LIGHT * (1 - depth) * 0.5 + CHOC * 0.5 + (CHOC_DARK - CHOC) * depth * 0.8
            add(img, x, y, c)
        add(img, x, s, FOAM, 1.0)     # foamy crest on the surface
        add(img, x, s + 1, FOAM, 0.45)
    # bubbles rising inside the chocolate
    for k in range(10):
        bx = 1 + (k * 37 % (W - 2))
        period = 1.4 + (k % 4) * 0.35
        ph = ((t / period) + k * 0.31) % 1.0
        by = (H - 2) - ph * ((H - 2) - surf)
        if by > surf + 1:
            add(img, bx, by, (255, 210, 140), 1.0)
    # steam wisps curling up above the surface
    for k in range(5):
        ph = ((t / 2.2) + k * 0.25) % 1.0
        sy = surf - 2 - ph * 22
        sx = 3 + k * 3.2 + 1.6 * math.sin(t * 2.4 + k + ph * 6)
        if sy >= 0:
            add(img, sx, sy, (240, 240, 240), 0.9 * (1 - ph))
            add(img, sx, sy - 1, (240, 240, 240), 0.6 * (1 - ph))
            add(img, sx + 1, sy - 2, (240, 240, 240), 0.35 * (1 - ph))
    if marsh:   # three marshmallows bobbing on the surface
        for k, mx in enumerate((3.5, 7.5, 11.5)):
            my = surf - 1.5 + 1.2 * math.sin(t * 3 + k * 2.1)
            for dx in (0, 1):
                for dy in (0, 1):
                    add(img, mx + dx, my + dy, (255, 250, 240))
    return img


def cup_fill(duration, path, fps=12):
    n = int(duration * fps)
    frames = []
    for f in range(n):
        t = f / fps
        level = min(1.0, (t / duration) ** 0.85)          # quick start, eases to full
        frames.append(cup_frame(t, level, marsh=level > 0.97))
    save(frames, path, int(1000 / fps))


def cup_hold(path, loop_s=4.0, fps=12):
    n = int(loop_s * fps)
    frames = [cup_frame(f / fps, 1.0, marsh=True) for f in range(n)]
    save(frames, path, int(1000 / fps))


def blob(img, cx, cy, r, rgb, a, tall=2.0):
    """Soft round puff (radius in strands; `tall` lights per strand-width, since strands are spread out)."""
    for y in range(int(cy - r * tall) - 1, int(cy + r * tall) + 2):
        for x in range(int(cx - r) - 1, int(cx + r) + 2):
            d = math.hypot((x - cx) / max(r, 0.5), (y - cy) / max(tall * r, 0.5))
            if d < 1:
                add(img, x, y, rgb, a * (1 - d) ** 0.7)


def snowfall(duration, path, fps=15):
    """Snow drifts down the tree and piles up at the base; a gust blows through halfway."""
    n = int(duration * fps)
    flakes = [[rng.uniform(0, W), rng.uniform(-H, H), rng.uniform(7, 16), rng.uniform(0, 6.3)] for _ in range(34)]
    pile = np.zeros(W)
    frames = []
    for f in range(n):
        t = f / fps
        img = np.zeros((H, W, 3))
        for y in range(H):   # faint night sky, a touch brighter near the ground
            img[y, :] = np.array([0, 4, 18]) + np.array([0, 6, 30]) * (y / H)
        gust = math.exp(-((t - duration * 0.55) / 1.4) ** 2) * 9
        for fl in flakes:
            fl[1] += fl[2] / fps
            fl[0] += (math.sin(t * 1.7 + fl[3]) * 1.2 + gust) / fps
            fl[0] %= W
            col = int(fl[0]) % W
            ground = H - 1 - pile[col]
            if fl[1] >= ground:
                pile[col] = min(14, pile[col] + 0.9)
                fl[:] = [rng.uniform(0, W), rng.uniform(-12, -1), rng.uniform(7, 16), rng.uniform(0, 6.3)]
                continue
            add(img, fl[0], fl[1], WHITE, 1.0)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                add(img, fl[0] + dx, fl[1] + dy, ICE, 0.6)
        sm = np.convolve(np.r_[pile[-1], pile, pile[0]], [0.25, 0.5, 0.25], "valid")
        for x in range(W):
            top = H - sm[x]
            for y in range(int(top), H):
                add(img, x, y, (235, 240, 255), 0.8 if y > top else 0.45)
        frames.append(img)
    save(frames, path, int(1000 / fps))


def switchback_train(duration, path, fps=15):
    """A little train climbs the tree on switchbacks, puffing steam; the star bursts when it reaches the top."""
    legs = [(1, 71), (14, 59), (1, 46), (14, 34), (2, 22), (12, 12), (7.5, 4)]
    seg = [math.hypot(legs[i + 1][0] - legs[i][0], legs[i + 1][1] - legs[i][1]) for i in range(len(legs) - 1)]
    total = sum(seg)

    def at(s):
        s = max(0.0, min(total, s))
        for i, L in enumerate(seg):
            if s <= L:
                f = s / L
                return legs[i][0] + (legs[i + 1][0] - legs[i][0]) * f, legs[i][1] + (legs[i + 1][1] - legs[i][1]) * f
            s -= L
        return legs[-1]

    arrive = duration - 2.6
    n = int(duration * fps)
    puffs, frames = [], []
    for f in range(n):
        t = f / fps
        img = np.zeros((H, W, 3))
        for y in range(H):               # snowy mountain: faint ice, brighter toward the peak
            img[y, :] = np.array([20, 35, 70]) * (1 - 0.5 * y / H)
        for i in range(len(legs) - 1):   # the track
            for k in range(int(seg[i] * 2)):
                x, y = at(sum(seg[:i]) + k / 2)
                add(img, x, y, (200, 215, 240), 0.35)
                add(img, x, y + 1, (120, 80, 50), 0.35)
        head = total * min(1.0, (t / arrive) ** 0.85)
        if t < arrive + 0.4:
            hx, hy = at(head)
            nx, ny = at(head + 1.5)
            def px2(s_, col, a):                               # 2 lights tall so it reads from the street
                x, y = at(s_)
                for dy in range(4):
                    add(img, x, y - dy, col, a)
            px2(head, WHITE, 1.0)                              # headlight
            for d, a in ((1.5, 0.7), (3, 0.45), (4.5, 0.25)):  # beam
                px2(head + d, (255, 240, 180), a)
            for d in (1, 2, 3):                                # locomotive
                px2(head - d, RED, 1.0)
            add(img, *at(head - 1.5), (40, 40, 40), 0)
            for c in range(5):                                 # lit passenger cars
                px2(head - 4.5 - c * 2.5, GOLD, 1.0)
                px2(head - 5.5 - c * 2.5, (180, 30, 15), 0.8)
            if f % 4 == 0:
                x, y = at(head - 1.5)
                puffs.append([x, y - 1, 1.0])
        nxt = []
        for p in puffs:
            p[1] -= 7 / fps
            p[2] -= 0.7 / fps
            if p[2] > 0:
                blob(img, p[0], p[1] - 3, 1.2 + (1 - p[2]) * 1.8, (235, 240, 250), p[2] * 0.85, tall=3.5)
                nxt.append(p)
        puffs = nxt
        if t >= arrive:                                        # star at the top bursts
            k = t - arrive
            for y in range(0, 4):
                add(img, 7, y, GOLD, 1.0)
                add(img, 8, y, GOLD, 1.0)
            r = k * 22
            for ang in range(0, 360, 20):
                a = math.radians(ang)
                for d in (r - 2, r - 1, r):
                    add(img, 7.5 + math.cos(a) * d * 0.25, 2 + math.sin(a) * d, (255, 230, 120), max(0, 1 - k / 2.6))
        frames.append(img)
    save(frames, path, int(1000 / fps))


def steam_stop(start, end, path, fps=15):
    """Steam puffs on every chug, getting further apart; a long hiss when it stops; then a warm platform glow."""
    n = int((end - start) * fps)
    chugs = [m - start for m in SLOW]
    stop = SLOW[-1] - start
    puffs, frames = [], []
    for f in range(n):
        t = f / fps
        img = np.zeros((H, W, 3))
        for c in chugs:
            if t - 1 / fps < c <= t and c < stop - 0.01:
                puffs.append([4.5 + rng.normal(0, 0.5), H - 4, 1.0, 1.0, rng.normal(0, 1) - 1.5])
                puffs.append([10.5 + rng.normal(0, 0.5), H - 4, 1.0, 1.0, rng.normal(0, 1) + 1.5])
        if t - 1 / fps < stop <= t:                            # the hiss: a wide cloud from the base
            for k in range(12):
                puffs.append([rng.uniform(1, 14), H - rng.uniform(2, 10), 1.0, 2.2, rng.normal(0, 3)])
        nxt = []
        for p in puffs:
            slow = p[3] > 1.5
            p[1] -= (7 if slow else 20) / fps
            p[0] += p[4] / fps
            p[2] -= (0.25 if slow else 0.45) / fps
            if p[2] > 0:
                r = (p[3] if slow else 1.4) + (1 - p[2]) * (3.0 if slow else 2.4)
                blob(img, p[0], p[1], r, (235, 242, 255), min(1, p[2] * 1.1), tall=4.5)
                nxt.append(p)
        puffs = nxt
        glow = (0.45 + 0.55 * min(1.0, max(0.0, (t - stop - 0.8) / 2.0))) * (0.85 + 0.15 * math.sin(t * 3))
        glow *= max(0.0, min(1.0, (end - start - t) / 1.2))
        if glow > 0:                                           # station lamps along the base
            for x in (2, 7, 8, 13):
                for y in range(H - 6, H):
                    add(img, x, y, (255, 170, 60), glow * (0.4 + 0.6 * (y - H + 6) / 6))
        frames.append(img)
    save(frames, path, int(1000 / fps))


def bell(start, end, path, fps=20):
    """A gold bell with a holly bow swings harder and harder, ringing on every beat."""
    beats = [b - start for b in BEATS if start <= b < end]
    n = int((end - start) * fps)
    px, py, L = 7.5, 13.0, 40.0

    def half_width(yl):
        if yl < 0 or yl > L:
            return -1
        f = yl / L
        w = 2.8 + 4.0 * f ** 1.4
        if yl < 3:
            w = 0.6 + 2.2 * math.sqrt(yl / 3)   # rounded crown
        if yl > L - 4:
            w += 1.3
        return w

    frames = []
    for f in range(n):
        t = f / fps
        img = np.zeros((H, W, 3))
        prev = max([b for b in beats if b <= t], default=0.0)
        nxt = min([b for b in beats if b > t], default=prev + 0.44)
        k = beats.index(prev) if prev in beats else 0
        ph = (t - prev) / max(1e-3, nxt - prev)
        amp = math.radians(8 + 22 * (t / (end - start)))
        side = 1 if k % 2 == 0 else -1
        th = side * amp * math.cos(math.pi * ph)               # swings to the other side each beat
        c, s = math.cos(-th), math.sin(-th)
        for y in range(H):
            for x in range(W):
                dx, dy = (x - px) * 2.2, y - py                # strands are spread wider than lights
                lx, ly = dx * c - dy * s, dx * s + dy * c
                w = half_width(ly)
                if w > 0 and abs(lx) / 2.2 <= w:
                    edge = abs(lx) / 2.2 / w
                    shade = 1.0 if lx < -0.8 else 0.75
                    col = (255, 230, 120) if (-0.55 < edge * np.sign(lx) < -0.2) else GOLD
                    add(img, x, y, col, shade * (0.55 if edge > 0.85 else 1.0))
        cx = px + math.sin(th * 1.25) * (L + 3) / 2.2          # clapper
        cy = py + math.cos(th * 1.25) * (L + 3)
        add(img, cx, cy, (255, 240, 200), 1.0)
        for x, y, col in ((6, 9, GREEN), (5, 10, GREEN), (9, 9, GREEN), (10, 10, GREEN), (7, 11, RED), (8, 11, RED), (8, 10, RED)):
            add(img, x, y, col, 1.0)                           # holly bow
        for b in beats:                                        # rings of sound from each strike
            age = t - b
            if 0 <= age < 0.6:
                r = 2 + age * 30
                for ang in range(0, 360, 12):
                    a = math.radians(ang)
                    add(img, px + math.cos(a) * r / 2.2, py + L + math.sin(a) * r, WHITE, 0.8 * (1 - age / 0.6))
        frames.append(img)
    save(frames, path, int(1000 / fps))


def frames_for(start, end):
    return [start + i / FPS for i in range(int(round((end - start) * FPS)))]


def blank():
    return np.zeros((H, W, 3))


def disk(img, cx, cy, r, rgb, a=1.0, aspect=2.2):
    """Filled circle in tree space (strands are spread wider than lights)."""
    for y in range(int(cy - r * aspect) - 1, int(cy + r * aspect) + 2):
        for x in range(int(cx - r) - 1, int(cx + r) + 2):
            if ((x - cx) / r) ** 2 + ((y - cy) / (r * aspect)) ** 2 <= 1:
                add(img, x, y, rgb, a)


def line(img, x0, y0, x1, y1, rgb, a=1.0):
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    for k in range(n + 1):
        f = k / n
        add(img, x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, rgb, a)


def boiler(start, end, path):
    """Firebox pressure that surges unevenly with the chugs and shakes harder until the whistle releases it."""
    ch = [c for c in chugs() if start <= c < end]
    frames = []
    for t in frames_for(start, end):
        img = blank()
        prog = (t - start) / (end - start)
        last = max([c for c in ch if c <= t], default=-9)
        kick = math.exp(-(t - last) / 0.12)                       # a surge on every chug
        shake = prog ** 2 * (rng.normal(0, 2.5))                  # pressure makes it unstable
        level = H - (12 + 48 * prog ** 1.3 + kick * (6 + 10 * prog) + shake)
        for y in range(H):
            depth = (y - level) / max(1, H - level)
            if depth < 0:
                continue
            core = min(1.0, depth * 1.4)
            col = (255, int(40 + 150 * (1 - core) * prog + 40 * kick), int(20 * kick * prog))
            for x in range(W):
                flick = 0.55 + 0.45 * math.sin(x * 1.7 + t * 23 + y * 0.4) * (0.4 + prog)
                add(img, x, y, col, min(1, (0.35 + 0.65 * core) * (0.55 + 0.45 * flick) * (0.6 + 0.4 * prog + 0.3 * kick)))
        for x in range(W):                                        # white-hot rim where the pressure pushes
            add(img, x, level + rng.normal(0, 0.6 * prog), (255, 230, 170), 0.5 + 0.5 * kick)
        if prog > 0.65:                                           # steam leaking near the top
            for _ in range(int((prog - 0.65) * 12)):
                blob(img, rng.uniform(2, 13), level - rng.uniform(2, 10), 0.8, STEAM, 0.25 + 0.3 * kick, tall=2.5)
        frames.append(img)
    save(frames, path, 1000 // FPS)


def whistle_blast(start, end, path, linger=1.2):
    """Full strength on the first frame: a white jet up the whole tree with billowing smoke, then drifting away."""
    frames, puffs = [], []
    dur = end - start
    for i, t in enumerate(frames_for(start, end + linger)):
        img = blank()
        k = t - start
        blowing = k < dur
        if blowing:
            for y in range(H):                                    # the jet, at full height from frame 0
                w = 1.2 + (H - y) / H * 2.5
                for x in range(W):
                    d = abs(x - 7.5) / w
                    if d < 1:
                        add(img, x, y, WHITE, (1 - d) ** 0.6 * (0.85 + 0.15 * math.sin(t * 40 + y)))
            for _ in range(3 if i else 14):                       # first frame bursts out a big cloud
                puffs.append([7.5 + rng.normal(0, 1.2), rng.uniform(0, 30), rng.normal(0, 4), rng.uniform(-12, -3), 1.0,
                              rng.uniform(1.0, 2.2)])
        nxt = []
        for p in puffs:
            p[0] += p[2] / FPS
            p[1] += p[3] / FPS
            p[4] -= (0.45 if blowing else 0.9) / FPS
            p[5] += 1.2 / FPS
            if p[4] > 0:
                shade = STEAM if p[4] > 0.5 else (170, 180, 200)  # cools to grey smoke
                blob(img, p[0], p[1], p[5], shade, p[4], tall=3.0)
                nxt.append(p)
        puffs = nxt
        frames.append(img)
    save(frames, path, 1000 // FPS)


def drive_wheel(start, end, path):
    """A locomotive drive wheel turning in step with the snowflake wheels (one spoke per eighth note)."""
    eighths = [BEATS[i] + (BEATS[i + 1] - BEATS[i]) * j / 2 for i in range(len(BEATS) - 1) for j in range(2)]
    cx, cy, r = 7.5, 46.0, 6.3
    frames = []
    for t in frames_for(start, end):
        img = blank()
        k = max([i for i, e in enumerate(eighths) if e <= t], default=0)
        frac = (t - eighths[k]) / max(1e-3, eighths[k + 1] - eighths[k]) if k + 1 < len(eighths) else 0
        ang = -(k + frac) * math.pi / 3                           # 60 degrees per eighth, same as the flakes
        for a in np.linspace(0, 2 * math.pi, 90):                 # tyre: white rim on red
            add(img, cx + math.cos(a) * r, cy + math.sin(a) * r * 2.2, WHITE, 1.0)
            add(img, cx + math.cos(a) * (r - 0.8), cy + math.sin(a) * (r - 0.8) * 2.2, RED, 0.9)
        for s in range(6):                                        # spokes; the lead spoke matches the flakes' lit arm
            a = ang + s * math.pi / 3
            col, al = (WHITE, 1.0) if s == k % 6 or s == 0 else (RED, 0.75)
            line(img, cx, cy, cx + math.cos(a) * (r - 1), cy + math.sin(a) * (r - 1) * 2.2, col, al)
        disk(img, cx, cy, 0.9, GOLD, 1.0)
        pin = (cx + math.cos(ang) * (r - 1.8), cy + math.sin(ang) * (r - 1.8) * 2.2)
        cross = (0.0, cy + math.sin(ang) * 3)                     # connecting rod to the crosshead
        line(img, pin[0], pin[1], cross[0], cross[1], (200, 200, 210), 0.9)
        for x in range(W):                                        # the rail
            add(img, x, cy + r * 2.2 + 3, (200, 210, 230), 0.7)
        if frac < 0.25 and k % 2 == 0:                            # chuff of steam on the beat
            blob(img, 3 + rng.uniform(-1, 1), 12, 1.6, STEAM, 0.7, tall=3)
        frames.append(img)
    save(frames, path, 1000 // FPS)


def snowman(start, end, path):
    """Snow keeps falling while a snowman builds itself on the bars: base, body, head, then face, buttons, hat."""
    bars = [b for b in BARS if start - 0.05 <= b < end]
    ev = {"base": bars[0], "body": bars[1], "head": bars[2], "face": bars[3], "hat": bars[4], "arms": bars[5]}
    flakes = [[rng.uniform(0, W), rng.uniform(0, H), rng.uniform(6, 13), rng.uniform(0, 6)] for _ in range(22)]
    SNOW = (235, 242, 255)
    frames = []
    for t in frames_for(start, end):
        img = blank()
        for y in range(H):
            img[y, :] = np.array([0, 4, 18]) + np.array([0, 6, 30]) * (y / H)
        for fl in flakes:
            fl[1] = (fl[1] + fl[2] / FPS) % H
            fl[0] = (fl[0] + math.sin(t * 1.5 + fl[3]) * 0.6 / FPS) % W
            add(img, fl[0], fl[1], WHITE, 0.9)
        for y in range(H - 4, H):
            for x in range(W):
                add(img, x, y, SNOW, 0.75)

        def ball(key, cx_end, cy, r, from_x):
            if t < ev[key]:
                return
            f = min(1.0, (t - ev[key]) / 0.6)
            cx = from_x + (cx_end - from_x) * (1 - (1 - f) ** 3)  # rolls in and settles
            disk(img, cx, cy, r * (0.5 + 0.5 * f), SNOW, 0.95)
        ball("base", 7.5, 63.5, 4.6, -6)
        ball("body", 7.5, 47.5, 3.5, 22)
        if t >= ev["head"]:                                      # head drops from the top
            f = min(1.0, (t - ev["head"]) / 0.5)
            disk(img, 7.5, 6 + (35.5 - 6) * f ** 2, 2.7, SNOW, 0.95)
        if t >= ev["face"]:
            pop = min(1.0, (t - ev["face"]) / 0.25)
            for x, y in ((6, 33), (9, 33)):                       # coal eyes = gaps in the snow
                img[y, x] = np.array([10, 10, 25])
            for x in (8, 9, 10):                                  # carrot nose
                add(img, x + (pop - 1) * 2, 36, (255, 110, 10), 1.0)
            for y in (44, 48, 52):                                # buttons
                img[y, 7] = np.array([10, 10, 25])
                img[y, 8] = np.array([10, 10, 25])
        if t >= ev["hat"]:                                       # top hat drops on, with a red band
            f = min(1.0, (t - ev["hat"]) / 0.35)
            yo = -10 * (1 - f)
            for y in range(23, 30):
                for x in range(5, 11):
                    add(img, x, y + yo, (25, 25, 40), 1.0)
            for x in range(5, 11):
                add(img, x, 28 + yo, RED, 1.0)
            for x in range(3, 13):
                add(img, x, 30 + yo, (60, 60, 80), 1.0)
        if t >= ev["arms"]:                                      # stick arms, the right one waving
            line(img, 4, 46, 0, 40, (150, 80, 30), 1.0)
            wave = math.sin((t - ev["arms"]) * 7) * 3
            line(img, 11, 46, 15, 40 + wave, (150, 80, 30), 1.0)
        frames.append(img)
    save(frames, path, 1000 // FPS)


def ticket(start, end, path):
    """A gold ticket slides up; a punch clips a hole on every downbeat and the bits fly off as confetti."""
    bars = [b for b in BARS if start + 0.5 <= b < end - 0.6]
    holes, bits, frames = [], [], []
    spots = [(5, 24), (10, 30), (5, 38), (10, 46), (6, 54), (9, 62)]
    for t in frames_for(start, end):
        img = blank()
        k = t - start
        rise = min(1.0, k / 0.8)
        leave = max(0.0, (t - (end - 0.6)) / 0.6)
        yo = (1 - rise) ** 2 * 60 - leave ** 2 * 80
        for y in range(16, 70):
            for x in range(2, 14):
                edge = x in (2, 13) or y in (16, 69)
                notch = (y in (16, 69)) and x in (7, 8)
                if notch:
                    continue
                shine = 0.75 + 0.25 * math.sin((x + y) * 0.5 - k * 6)
                add(img, x, y + yo, (255, 230, 120) if edge else GOLD, 1.0 if edge else 0.8 * shine)
        for b in bars:
            if t >= b and b not in [h[2] for h in holes]:
                sx, sy = spots[len(holes) % len(spots)]
                holes.append((sx, sy, b))
                for _ in range(10):
                    bits.append([sx, sy + yo, rng.normal(0, 7), rng.uniform(-14, -4), 1.0])
        for sx, sy, b in holes:                                   # punched holes (dark) with a white flash
            age = t - b
            for dx in (0, 1):
                for dy in (0, 1, 2):
                    yy = int(round(sy + dy + yo))
                    if 0 <= yy < H:
                        img[yy, sx + dx] = np.array([0, 0, 0]) if age > 0.08 else np.array([255, 255, 255])
        nxt = []
        for p in bits:
            p[3] += 30 / FPS
            p[0] += p[2] / FPS
            p[1] += p[3] / FPS
            p[4] -= 0.7 / FPS
            if p[4] > 0:
                add(img, p[0], p[1], GOLD if rng.random() < 0.6 else WHITE, p[4])
                nxt.append(p)
        bits = nxt
        frames.append(img)
    save(frames, path, 1000 // FPS)


def present(start, end, path, burst):
    """A wrapped present shakes harder on every beat; on the burst the bow pops, the lid flies, sparkles shoot up."""
    beats = [b for b in BEATS if start <= b < burst]
    sparks, frames = [], []
    for t in frames_for(start, end):
        img = blank()
        last = max([b for b in beats if b <= t], default=start)
        jolt = math.exp(-(t - last) / 0.1) * (1 + 3 * (t - start) / (burst - start))
        dx = math.sin((t - last) * 40) * jolt * 0.6
        lid_y = 0.0
        if t >= burst:
            lid_y = -((t - burst) * 60)
        for y in range(36, 72):                                    # box
            for x in range(1, 15):
                ribbon = x in (7, 8) or y in (52, 53)
                add(img, x + dx, y, GREEN if ribbon else RED, 1.0 if ribbon else 0.85)
        for y in range(30, 36):                                    # lid
            for x in range(0, 16):
                ribbon = x in (7, 8)
                add(img, x + dx, y + lid_y, GREEN if ribbon else (255, 60, 50), 1.0)
        if t < burst + 0.05:                                       # bow
            for x, y in ((5, 27), (6, 28), (6, 26), (9, 26), (9, 28), (10, 27), (7, 29), (8, 29)):
                add(img, x + dx, y, GREEN, 1.0)
        if burst <= t < burst + 1 / FPS + 1e-6:
            for _ in range(70):
                sparks.append([rng.uniform(3, 12), 34, rng.normal(0, 6), rng.uniform(-55, -20), 1.0,
                               [WHITE, GOLD, GREEN, RED][rng.integers(4)]])
        nxt = []
        for p in sparks:
            p[3] += 25 / FPS
            p[0] += p[2] / FPS
            p[1] += p[3] / FPS
            p[4] -= 0.55 / FPS
            if p[4] > 0 and p[1] < H:
                add(img, p[0], p[1], p[5], p[4])
                nxt.append(p)
        sparks = nxt
        frames.append(img)
    save(frames, path, 1000 // FPS)


def lantern(start, end, path, then=None):
    """One conductor's lantern swinging slowly in the dark; dims while `then` (a GIF's first frame) fades in."""
    mug = None
    if then:
        nxt = Image.open(then)
        nxt.seek(0)
        mug = np.asarray(nxt.convert("RGB").resize((W, H))).astype(float)
    frames = []
    for t in frames_for(start, end):
        img = blank()
        k = (t - start) / (end - start)
        dim = 1.0 if k < 0.55 else max(0.0, 1 - (k - 0.55) / 0.45)
        sw = math.sin((t - start) * 2.1) * 0.35
        px, py, L = 7.5, 0.0, 34.0
        lx, ly = px + math.sin(sw) * L / 2.2, py + math.cos(sw) * L
        line(img, px, py, lx, ly - 4, (120, 110, 100), 0.6 * dim)
        for y in range(int(ly - 4), int(ly + 5)):
            for x in range(int(lx - 2), int(lx + 3)):
                body = abs(x - lx) <= 1.6
                add(img, x, y, (255, 200, 90) if body else (120, 60, 20), dim * (1.0 if body else 0.7))
        blob(img, lx, ly, 3.0, (255, 150, 40), 0.35 * dim, tall=2.5)
        if mug is not None and k > 0.5:
            img = np.maximum(img, mug * min(1.0, (k - 0.5) / 0.5))
        frames.append(img)
    save(frames, path, 1000 // FPS)


def flames(start, end, path, hits):
    """Low embers that leap up the whole tree on each 'hot hot' and die back between; smaller flares on downbeats."""
    small = [b for b in BARS if start <= b < end]
    frames = []
    heat = np.zeros(W)
    for t in frames_for(start, end):
        img = blank()
        last = max([h for h in hits if h <= t], default=-9)
        boost = math.exp(-(t - last) / 0.35)
        lastb = max([b for b in small if b <= t], default=-9)
        boost = max(boost, 0.4 * math.exp(-(t - lastb) / 0.4))
        for x in range(W):
            target = 10 + 6 * math.sin(t * 5 + x * 1.3) + boost * (52 + 8 * math.sin(x * 2.1 + t * 9))
            heat[x] += (target - heat[x]) * (0.9 if target > heat[x] else 0.25)
            top = H - heat[x]
            for y in range(int(top), H):
                d = (y - top) / max(1, heat[x])
                col = (255, int(210 * (1 - d) ** 1.5 + 30), int(80 * max(0, 0.4 - d))) if d < 0.5 else (255, int(60 * (1 - d)), 0)
                flick = 0.7 + 0.3 * math.sin(y * 0.9 + t * 30 + x)
                add(img, x, y, col, min(1, (0.4 + 0.6 * d) * flick + 0.2))
        frames.append(img)
    save(frames, path, 1000 // FPS)


def fireworks(start, end, path, hits, star_at):
    """Shells launch from the base and burst on the musical hits; the last burst draws a star at the top."""
    cols = [RED, GREEN, WHITE, GOLD, ICE]
    shells = [(h - 0.45, h, rng.uniform(3, 12), rng.uniform(10, 35), cols[i % len(cols)]) for i, h in enumerate(hits)]
    parts, frames, done = [], [], set()
    for t in frames_for(start, end):
        img = blank()
        for i, (l0, b, x, y, c) in enumerate(shells):
            if l0 <= t < b:                                        # rising trail
                f = (t - l0) / (b - l0)
                for k in range(4):
                    add(img, x, H - 1 - (H - 1 - y) * f + k * 2, (255, 210, 150), 1 - k * 0.25)
            if t >= b and i not in done:
                done.add(i)
                for a in rng.uniform(0, 2 * math.pi, 46):          # a filled burst, not a thin ring
                    sp = rng.uniform(4, 15)
                    parts.append([x, y, math.cos(a) * sp / 2.2, math.sin(a) * sp, 1.0, c])
                disk(img, x, y, 1.6, WHITE, 1.0)
        nxt = []
        for p in parts:
            p[3] += 14 / FPS
            p[0] += p[2] / FPS
            p[1] += p[3] / FPS
            p[4] -= 0.8 / FPS
            if p[4] > 0:
                add(img, p[0], p[1], p[5], p[4])
                add(img, p[0] - p[2] / FPS, p[1] - p[3] / FPS, p[5], p[4] * 0.5)   # short trail
                nxt.append(p)
        parts = nxt
        if t >= star_at:                                           # star at the top
            f = min(1.0, (t - star_at) / 0.3)
            for a in range(5):
                ang = -math.pi / 2 + a * 2 * math.pi / 5
                line(img, 7.5, 10, 7.5 + math.cos(ang) * 6 * f, 10 + math.sin(ang) * 9 * f, (255, 235, 140), 1.0)
            disk(img, 7.5, 10, 1.4 * f + 0.1, WHITE, 1.0)
        frames.append(img)
    save(frames, path, 1000 // FPS)


def taillight(start, end, path):
    """The train's red taillight climbs the tree and shrinks into the distance; only the star is left, then it fades."""
    frames = []
    for t in frames_for(start, end):
        img = blank()
        k = (t - start) / (end - start)
        fade = 1.0 if k < 0.75 else max(0.0, 1 - (k - 0.75) / 0.25)
        for y in range(8, H):                                      # rails converging toward the top
            f = (y - 8) / (H - 8)
            add(img, 7.5 - 7 * f, y, (150, 160, 190), 0.35 * fade)
            add(img, 7.5 + 7 * f, y, (150, 160, 190), 0.35 * fade)
        f = min(1.0, k / 0.7)
        y = (H - 6) - (H - 20) * (1 - (1 - f) ** 2)
        size = 2.4 * (1 - f) + 0.5
        if f < 1:
            disk(img, 7.5, y, size, RED, 1.0 * fade)
            blob(img, 7.5, y, size * 2, (255, 40, 20), 0.3 * fade, tall=2)
        for a in range(5):                                         # the star stays
            ang = -math.pi / 2 + a * 2 * math.pi / 5
            line(img, 7.5, 6, 7.5 + math.cos(ang) * 4, 6 + math.sin(ang) * 5.5, (255, 225, 120), fade)
        frames.append(img)
    save(frames, path, 1000 // FPS)


# ----------------------------------------------------------------------------- command line
SCENES = {
    "boiler": ("Firebox pressure that surges on each chug (--hits, else eighths) and shakes harder to the end.",
               lambda a: boiler(a.start, a.end, a.out)),
    "steam_blast": ("A train whistle: full-height white jet from the first frame, smoke billows and drifts "
                    "(the GIF runs 1.2 s past --end for the smoke to clear).",
                    lambda a: whistle_blast(a.start, a.end, a.out)),
    "drive_wheel": ("A locomotive wheel turning one spoke per eighth note, rod pumping, steam on the beat.",
                    lambda a: drive_wheel(a.start, a.end, a.out)),
    "snowfall": ("Snow drifting down with a gust halfway, piling up at the base.",
                 lambda a: snowfall(a.end - a.start, a.out)),
    "snowman": ("A snowman building itself on the bars: base, body, head, face, hat, waving arm (needs 6 bars).",
                lambda a: snowman(a.start, a.end, a.out)),
    "ticket": ("A gold ticket slides up; a punch clips a hole on each downbeat, confetti flies.",
               lambda a: ticket(a.start, a.end, a.out)),
    "present": ("A wrapped present shaking harder on each beat until it bursts (--burst, else 1.8 s before the end).",
                lambda a: present(a.start, a.end, a.out, burst=a.burst or a.end - 1.8)),
    "train_climb": ("A lit train climbing switchbacks to the top; the star bursts when it arrives.",
                    lambda a: switchback_train(a.end - a.start, a.out)),
    "steam_stop": ("Steam puffs getting further apart, a big hiss at the stop, then warm lamps along the base.",
                   lambda a: steam_stop(a.start, a.end, a.out)),
    "lantern": ("A swinging lantern in the dark that dims while --then (a GIF's first frame) fades in.",
                lambda a: lantern(a.start, a.end, a.out, then=a.then)),
    "cup_fill": ("A red mug filling with sloshing cocoa: foam, bubbles, steam, marshmallows at the top.",
                 lambda a: cup_fill(a.end - a.start, a.out)),
    "cup_hold": ("The full mug, sloshing and steaming, as a 4 s loop.",
                 lambda a: cup_hold(a.out)),
    "flames": ("Low embers that leap up the tree on each --hits time and flare softly on downbeats.",
               lambda a: flames(a.start, a.end, a.out, HITS)),
    "fireworks": ("Shells launch and burst on --hits (else the downbeats); a star draws at the top (--star).",
                  lambda a: fireworks(a.start, a.end, a.out, HITS or [b for b in BARS if a.start + 0.5 <= b < a.end],
                                      star_at=a.star or a.end - 1.4)),
    "bell": ("A gold bell with a holly bow swinging harder, ringing on every beat.",
             lambda a: bell(a.start, a.end, a.out)),
    "taillight": ("Goodnight: the red taillight climbs and shrinks into the distance; the star fades last.",
                  lambda a: taillight(a.start, a.end, a.out)),
}
NEEDS_BEATS = {"boiler", "drive_wheel", "snowman", "ticket", "present", "flames", "fireworks", "bell"}


def gif_at(path, t):
    """The frame showing at time t (GIF frames can be merged, so never index by frame number)."""
    g = Image.open(path)
    acc = 0.0
    for i in range(g.n_frames):
        g.seek(i)
        acc += g.info.get("duration", 50) / 1000
        if acc > t:
            break
    return g.convert("RGB")


def main(argv=None):
    global OUT_SIZE, BEATS, BARS, HITS, SLOW
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenes", help="list the scenes")
    r = sub.add_parser("render", help="render one scene to a GIF")
    r.add_argument("scene", choices=sorted(SCENES))
    r.add_argument("--start", type=float, required=True, help="song time (s) the picture starts")
    r.add_argument("--end", type=float, required=True, help="song time (s) the picture ends")
    r.add_argument("--out", required=True)
    r.add_argument("--analysis", help="song.analysis.json from lor_audio.py (beats and bars)")
    r.add_argument("--hits", help="comma-separated song times (chugs, hits, bursts)")
    r.add_argument("--size", default="16x75", help="WIDTHxHEIGHT of the prop's buffer (default 16x75)")
    r.add_argument("--burst", type=float, help="present: when it bursts")
    r.add_argument("--star", type=float, help="fireworks: when the star draws")
    r.add_argument("--then", help="lantern: GIF whose first frame fades in at the end")
    s = sub.add_parser("sheet", help="contact sheet of a GIF sampled by time")
    s.add_argument("gif")
    s.add_argument("--out", required=True)
    s.add_argument("--count", type=int, default=8)
    s.add_argument("--scale", type=int, default=5)
    a = ap.parse_args(argv)

    if a.cmd == "scenes":
        for name, (desc, _) in sorted(SCENES.items()):
            print(f"{name:12} {desc}{'  [needs --analysis]' if name in NEEDS_BEATS else ''}")
        return
    if a.cmd == "sheet":
        g = Image.open(a.gif)
        total = sum((g.seek(i) or g.info.get("duration", 50)) for i in range(g.n_frames)) / 1000
        w, h = g.size
        sheet = Image.new("RGB", (a.count * (w * a.scale + 8), h * a.scale + 22), (30, 30, 30))
        from PIL import ImageDraw
        d = ImageDraw.Draw(sheet)
        for k in range(a.count):
            t = total * (k + 0.5) / a.count
            sheet.paste(gif_at(a.gif, t).resize((w * a.scale, h * a.scale), Image.NEAREST), (k * (w * a.scale + 8), 22))
            d.text((k * (w * a.scale + 8) + 2, 4), f"{t:.1f}s", fill=(220, 220, 220))
        sheet.save(a.out)
        print(f"{a.out}: {a.count} frames of {total:.1f}s")
        return

    w, h = (int(v) for v in a.size.lower().split("x"))
    OUT_SIZE = (w, h)
    if a.analysis:
        an = json.loads(Path(a.analysis).read_text())
        BEATS, BARS = an["beats"], an["downbeats"]
    elif a.scene in NEEDS_BEATS:
        sys.exit(f"{a.scene} is timed to the music: pass --analysis song.analysis.json")
    HITS = [float(x) for x in a.hits.split(",")] if a.hits else []
    SLOW = HITS or slowdown(a.start, a.end)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    SCENES[a.scene][1](a)


if __name__ == "__main__":
    main()
