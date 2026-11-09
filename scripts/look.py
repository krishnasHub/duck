"""A rough description of what someone is wearing, so the follower can tell two people apart.

Colour histograms of the upper and lower body. No faces and no learned identity: it's only clothes, so it changes when they
change clothes and can't separate two people dressed alike. Kept in memory only.
"""
import numpy as np

HUES = 8
SATURATIONS = 3
VALUES = 4
# Below this saturation or at very low brightness, hue is mostly noise, so those pixels only count by brightness.
GREY_SATURATION = 40
DARK_VALUE = 40
PARTS = ((0.15, 0.5), (0.5, 0.9))
INNER_WIDTH = 0.6
MIN_PIXELS = 30


def _histogram(pixels):
    hue, saturation, value = pixels[:, 0].astype(int), pixels[:, 1].astype(int), pixels[:, 2].astype(int)
    colourful = (saturation >= GREY_SATURATION) & (value >= DARK_VALUE)
    counts = np.zeros(HUES * SATURATIONS + VALUES, dtype=np.float32)
    joint = (hue[colourful] * HUES // 256) * SATURATIONS + (saturation[colourful] * SATURATIONS // 256)
    np.add.at(counts, joint, 1)
    np.add.at(counts, HUES * SATURATIONS + value[~colourful] * VALUES // 256, 1)
    return counts / max(counts.sum(), 1)


def signature(hsv, box):
    """hsv is the frame as a height x width x 3 array. box is (x1, y1, x2, y2) in fractions. Returns None if it's too small to tell."""
    height, width = hsv.shape[:2]
    x1, y1, x2, y2 = box
    margin = (x2 - x1) * (1 - INNER_WIDTH) / 2
    left, right = int((x1 + margin) * width), int((x2 - margin) * width)
    parts = []
    for top, bottom in PARTS:
        upper = int((y1 + (y2 - y1) * top) * height)
        lower = int((y1 + (y2 - y1) * bottom) * height)
        pixels = hsv[upper:lower, left:right].reshape(-1, 3)
        if len(pixels) < MIN_PIXELS:
            return None
        parts.append(_histogram(pixels))
    return np.stack(parts)


def similarity(one, other):
    """From 0 to 1, where 1 means the same colours in the same places. None if either couldn't be read."""
    if one is None or other is None:
        return None
    return float(np.minimum(one, other).sum(axis=1).mean())


def blend(old, new, amount=0.05):
    """Let a remembered look drift slowly with the light, without being captured by one bad frame."""
    return (1 - amount) * old + amount * new
