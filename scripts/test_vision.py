"""The real detector with the real follow logic, on real photos, with a crop standing in for a turning camera.

Closes the whole loop from picture to steering and back to picture. A still photo means nobody moves, so this checks the
parts connect and the head settles on a person. It says nothing about following someone who walks.
"""
import statistics
import sys
import time

from PIL import Image

from detect import MODELS, Detector, describe
from follow import Box, Follower

VIEW = 0.55
PAN_SPEED = 0.25
HZ = 10
FRAMES = 120
CENTRED = 0.08


def boxes_in(found):
    return [Box((d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2, d.x2 - d.x1, d.y2 - d.y1, d.score) for d in found if d.label == "person"]


def crop(photo, pan):
    seen = photo.width * VIEW
    left = pan * (photo.width - seen)
    return photo.crop((int(left), 0, int(left + seen), photo.height))


detector = Detector("yolox_nano", threads=4)
results = []
for name in ("street.jpg", "street2.jpg"):
    photo = Image.open(MODELS / name).convert("RGB")
    print(f"{name}: he sees {describe(detector.detect(photo))}")
    for start in (0.0, 1.0):
        follower = Follower()
        pan = start
        off, states, times = [], [], []
        for frame in range(FRAMES):
            view = crop(photo, pan)
            began = time.perf_counter()
            found = detector.detect(view)
            times.append(time.perf_counter() - began)
            command = follower.update(boxes_in(found), frame / HZ)
            states.append(command.state)
            target = follower.tracker.target
            off.append(abs(target.cx - 0.5) if target and command.state == "following" else None)
            pan = max(0.0, min(1.0, pan + command.pan * PAN_SPEED / HZ))
        seen = [value for value in off[-20:] if value is not None]
        at_edge = pan in (0.0, 1.0)
        settled = len(seen) >= 15 and statistics.median(seen) < CENTRED
        # Nobody in view means it should never have moved at all, and that's correct, because it can't know anyone is there.
        nobody = not boxes_in(detector.detect(crop(photo, start))) and pan == start and "following" not in states
        # A person who can't be centred because the photo ends there is the crop's limit, not a fault.
        results.append(settled or nobody or (at_edge and len(seen) >= 15))
        verdict = "settled" if settled else "nobody in view, so it stayed still" if nobody else "at the edge of the photo" if at_edge else "NOT SETTLED"
        print(f"  from {start:.0f}: {verdict} at pan {pan:.2f}, "
              f"off centre {statistics.median(seen) if seen else float('nan'):.3f}, detector {statistics.median(times) * 1000:.0f} ms, "
              f"following on {states.count('following')} of {FRAMES} frames")
print("all settled" if all(results) else "some didn't settle")
sys.exit(0 if all(results) else 1)
