"""Try the follow logic in a simple simulated world: a wheeled duck with a camera, and people walking about.

This tests the logic and catches unsafe behaviour. It isn't reality: real wheels slip, and real detectors miss people in
ways this noise doesn't capture. Numbers here say nothing about how well real hardware will follow.
"""
import math
import random

from follow import Box, Follower

FIELD_OF_VIEW = math.radians(62)  # roughly an IMX219 camera module
VERTICAL_VIEW = math.radians(48)
PERSON_HEIGHT = 1.7
PERSON_WIDTH = 0.5
MAX_TURN = 1.5  # radians per second at full pan
MAX_SPEED = 1.2  # metres per second at full forward
COLLISION = 0.6


class World:
    def __init__(self, seed, people, hz=20, latency=0.0, noise=0.006, dropout=0.03):
        self.random = random.Random(seed)
        self.people = people
        self.dt = 1 / hz
        self.x, self.y, self.heading = 0.0, 0.0, 0.0
        self.noise, self.dropout = noise, dropout
        self.delay = max(0, round(latency * hz))
        self.queue = []
        self.t = 0.0

    def view(self):
        boxes = []
        for name, walk in self.people.items():
            place = walk(self.t)
            if place is None:
                continue
            dx, dy = place[0] - self.x, place[1] - self.y
            # In this world +x is ahead at heading 0, and +y is to the right.
            bearing = (math.atan2(dy, dx) - self.heading + math.pi) % (2 * math.pi) - math.pi
            distance = math.hypot(dx, dy)
            if abs(bearing) > FIELD_OF_VIEW / 2 or distance < 0.3 or self.random.random() < self.dropout:
                continue
            h = PERSON_HEIGHT / distance / (2 * math.tan(VERTICAL_VIEW / 2))
            w = PERSON_WIDTH / distance / (2 * math.tan(FIELD_OF_VIEW / 2))
            boxes.append(Box(0.5 + bearing / FIELD_OF_VIEW + self.random.gauss(0, self.noise), 0.5 + self.random.gauss(0, self.noise),
                             w, h * (1 + self.random.gauss(0, 0.02)), 0.9, name))
        self.queue.append(boxes)
        return self.queue.pop(0) if len(self.queue) > self.delay else []

    def move(self, command):
        self.heading += command.pan * MAX_TURN * self.dt
        self.x += math.cos(self.heading) * command.forward * MAX_SPEED * self.dt
        self.y += math.sin(self.heading) * command.forward * MAX_SPEED * self.dt
        self.t += self.dt

    def distance_to(self, name):
        place = self.people[name](self.t)
        return math.hypot(place[0] - self.x, place[1] - self.y) if place else None


def run(world, seconds, watch="me"):
    """Returns per-frame records of command, distance and who the tracker was on."""
    follower = Follower()
    records = []
    while world.t < seconds:
        boxes = world.view()
        command = follower.update(boxes, world.t)
        target = follower.tracker.target
        records.append({"t": world.t, "c": command, "d": world.distance_to(watch), "on": target.tag if target else None, "seen": any(b.tag == watch for b in boxes)})
        world.move(command)
    return records, follower


def line(x0, y0, vx, vy, start=0.0):
    return lambda t: (x0 + vx * max(0, t - start), y0 + vy * max(0, t - start))


def s_curve(t):
    """A person strolling at about 0.8 m/s along a winding path."""
    return (3.5 + 0.75 * t, 2.0 * math.sin(t / 3))


def stops(t):
    return (3.5 + 0.8 * min(t, 10), 0.0)


results = []


def check(name, passed, detail=""):
    results.append(passed)
    print(f"{'ok  ' if passed else 'FAIL'} {name}{' (' + detail + ')' if detail else ''}")


# Walking a winding path.
records, _ = run(World(1, {"me": s_curve}), 60)
late = [r for r in records if r["t"] > 5]
on_me = sum(r["on"] == "me" for r in late) / len(late)
mean = sum(r["d"] for r in late) / len(late)
check("follows a winding walk", on_me > 0.95 and 2.5 < mean < 6, f"on target {on_me:.0%}, mean distance {mean:.1f} m, closest {min(r['d'] for r in records):.1f} m")
check("never hits the person", min(r["d"] for r in records) > COLLISION)

# The same walk at the slower rates the Jetson may manage while he's also talking.
for hz, latency in ((10, 0.1), (5, 0.2), (3, 0.3)):
    records, _ = run(World(2, {"me": s_curve}, hz=hz, latency=latency), 60)
    late = [r for r in records if r["t"] > 8]
    on_me = sum(r["on"] == "me" for r in late) / len(late)
    closest = min(r["d"] for r in records)
    check(f"still follows at {hz} frames/s with {latency}s delay", on_me > 0.8 and closest > COLLISION, f"on target {on_me:.0%}, closest {closest:.1f} m")

# Person stops: the duck should settle at a distance, not creep or hunt.
records, _ = run(World(3, {"me": stops}), 40)
end = [r for r in records if r["t"] > 32]
speed = max(abs(r["c"].forward) for r in end)
turning = sum(abs(r["c"].pan) for r in end) / len(end)
check("settles when they stop", speed < 0.15 and turning < 0.1, f"max forward {speed:.2f}, mean pan {turning:.3f}, stopped at {end[-1]['d']:.1f} m")

# Person walks straight at the duck: it mustn't drive forward once they're close.
records, _ = run(World(4, {"me": line(5, 0, -0.8, 0, start=5)}), 12)
close = [r for r in records if r["d"] < 2.6]
check("doesn't drive at someone close", bool(close) and max(r["c"].forward for r in close) == 0, f"max forward when close {max((r['c'].forward for r in close), default=-1):.2f}")

# Person hidden for 5 seconds: no driving blind, and resume afterward.
hidden_walk = lambda t: None if 15 < t < 20 else (3.5 + 0.3 * t, 0.0)
records, _ = run(World(5, {"me": hidden_walk}, dropout=0), 40, watch="me")
blind = [r for r in records if 15.1 < r["t"] < 20]
check("stops driving the moment they vanish", max(r["c"].forward for r in blind) == 0)
states = [r["c"].state for r in blind]
check("waits, then looks for them", "hidden" in states and "searching" in states)
check("picks them up again", any(r["on"] == "me" and r["c"].state == "following" for r in records if r["t"] > 25))

# Someone else crosses between duck and person, at about the same size: the hard case.
crosser = line(3.5, -3.0, 0.3, 1.0, start=8)
records, _ = run(World(6, {"me": stops, "other": crosser}), 22)
after = [r for r in records if r["t"] > 6]
check("stays with me when someone walks past", all(r["on"] in ("me", None) for r in after), f"on other for {sum(r['on'] == 'other' for r in after)} of {len(after)} frames")
# Someone much closer: stay on me, but don't drive toward them.
stepping_in = lambda t: (8.0, max(0.0, 3.0 - max(0, t - 4)))
records, _ = run(World(7, {"me": stops, "other": stepping_in}), 25, watch="other")
closest = min(r["d"] for r in records)
check("won't drive into a bystander in the way", closest > 2.5 and records[-1]["c"].forward == 0, f"closest {closest:.1f} m, final forward {records[-1]['c'].forward:.2f}")

# Nobody there, then a false sighting for a single frame.
follower = Follower()
commands = [follower.update([], t * 0.05) for t in range(40)]
check("stays still with nobody there", all(c.forward == 0 and c.pan == 0 for c in commands))
follower = Follower()
blip = follower.update([Box(0.2, 0.5, 0.1, 0.3)], 0.0)
commands = [follower.update([], 0.05 * t) for t in range(1, 200)]
check("one false sighting doesn't move it", blip.forward == 0 and blip.pan == 0 and all(c.forward == 0 for c in commands) and max(abs(c.pan) for c in commands) <= 0.25)

# A low score is ignored.
follower = Follower()
commands = [follower.update([Box(0.2, 0.5, 0.1, 0.3, score=0.2)], 0.05 * t) for t in range(20)]
check("ignores unsure detections", all(c.pan == 0 and c.forward == 0 for c in commands))

# The vision dies mid-follow.
follower = Follower()
for t in range(40):
    follower.update([Box(0.6, 0.5, 0.1, 0.3)], 0.05 * t)
running = follower.forward > 0
stale = follower.watchdog(2.0 + 0.7)
check("stops when frames stop arriving", running and stale is not None and stale.forward == 0 and stale.pan == 0 and follower.forward == 0)
check("watchdog is quiet while frames arrive", follower.update([Box(0.6, 0.5, 0.1, 0.3)], 2.75) is not None and follower.watchdog(2.8) is None)

# Halt beats everything, and holds until resumed.
follower = Follower()
for t in range(40):
    follower.update([Box(0.6, 0.5, 0.1, 0.3)], 0.05 * t)
follower.halt()
held = [follower.update([Box(0.6, 0.5, 0.1, 0.3)], 2 + 0.05 * t) for t in range(40)]
check("halt stops it and it stays stopped", all(c.forward == 0 and c.pan == 0 and c.state == "halted" for c in held))
follower.resume()
restarted = [follower.update([Box(0.6, 0.5, 0.1, 0.3)], 4 + 0.05 * t) for t in range(10)]
check("resume needs fresh confirmation", restarted[0].state == "confirming" and restarted[-1].state == "following")

# Every command in every test stays in range.
records, _ = run(World(8, {"me": s_curve}, noise=0.05, dropout=0.2), 40)
check("commands stay in range under heavy noise", all(abs(r["c"].pan) <= 1 and abs(r["c"].tilt) <= 1 and 0 <= r["c"].forward <= 1 for r in records))

print(f"{sum(results)} of {len(results)} passed")
raise SystemExit(0 if all(results) else 1)
