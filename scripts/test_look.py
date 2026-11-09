"""Telling people apart by clothes: signatures on made-up pictures, then the follower's rules with made-up looks."""
import sys

import numpy as np

from follow import Box, Follower
from look import signature, similarity

HZ = 10
results = []


def check(name, passed):
    results.append(passed)
    print(f"{'ok  ' if passed else 'FAIL'} {name}")


def picture(top, bottom):
    """A person-shaped picture: an upper colour over a lower colour, as hue, saturation, value."""
    image = np.zeros((100, 50, 3), dtype=np.uint8)
    image[:50] = top
    image[50:] = bottom
    return image


RED, BLUE, BEIGE = (0, 220, 200), (170, 220, 200), (25, 80, 200)
WHOLE = (0, 0, 1, 1)
dark_beige = signature(picture((0, 0, 30), BEIGE), WHOLE)
check("same clothes match fully", similarity(dark_beige, signature(picture((0, 0, 30), BEIGE), WHOLE)) > 0.99)
check("different colours don't match", similarity(signature(picture(RED, RED), WHOLE), signature(picture(BLUE, BLUE), WHOLE)) < 0.1)
check("same top with different trousers is only a part match", 0.4 < similarity(dark_beige, signature(picture((0, 0, 30), (0, 0, 30)), WHOLE)) < 0.75)
check("a tiny box can't be read", signature(picture(RED, RED), (0.5, 0.5, 0.52, 0.51)) is None)
check("an unreadable look compares as unknown", similarity(None, dark_beige) is None)

ME = signature(picture(RED, BEIGE), WHOLE)
STRANGER = signature(picture(BLUE, BLUE), WHOLE)


def person(x, seen=ME, h=0.4, tag="me"):
    return Box(x, 0.5, 0.15, h, look=seen, tag=tag)


# A stranger steps exactly where the target just was. Position alone would take them.
follower = Follower()
for frame in range(10):
    follower.update([person(0.5)], frame / HZ)
command = follower.update([person(0.52, STRANGER, tag="stranger")], 1.0)
check("won't hand over to a differently dressed person at the same spot", command.state == "hidden")

follower = Follower()
for frame in range(10):
    follower.update([person(0.5)], frame / HZ)
follower.update([person(0.52, STRANGER, tag="stranger")], 1.0)
for frame in range(3):
    command = follower.update([person(0.53)], 1.1 + frame / HZ)
check("picks the same person back up after that, once confirmed", command.state == "following" and follower.tracker.target.tag == "me")

# Enrolled: strangers are ignored however long the owner is away, and even when they're the biggest thing in view.
follower = Follower()
check("enrolling with nobody in view does nothing", not follower.enroll())
for frame in range(10):
    follower.update([person(0.5)], frame / HZ)
check("can enroll whoever it's following", follower.enroll())
now = 1.0
states = set()
for frame in range(100):
    now += 1 / HZ
    states.add(follower.update([person(0.5, STRANGER, h=0.5, tag="stranger")], now).state)
check("an enrolled follower never follows a stranger", "following" not in states and "confirming" not in states)
for frame in range(5):
    now += 1 / HZ
    command = follower.update([person(0.5, STRANGER, h=0.5, tag="stranger"), person(0.2)], now)
check("the owner is found again among strangers", command.state == "following" and follower.tracker.target.tag == "me")
follower.update([person(0.2, seen=None)], now + 0.1)
check("an unreadable box isn't taken for the owner", follower.tracker.target.look is not None)

# Without any looks at all, it behaves as it did before.
follower = Follower()
for frame in range(10):
    command = follower.update([Box(0.5, 0.5, 0.15, 0.4)], frame / HZ)
check("works with no looks supplied", command.state == "following")

print(f"{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
