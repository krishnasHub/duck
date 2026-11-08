"""Turn "where is the person in the picture" into steering, for a pan-tilt head, then wheels, then a drone.

Pure logic with no camera, motors or model, so it can be tested in simulation and carried to any of them unchanged.
Safety comes first in the design: it stops when it isn't sure, and every command is limited.
"""
from dataclasses import dataclass


@dataclass
class Box:
    """A person's box, as fractions of the image. `tag` lets a simulation check who was really followed."""
    cx: float
    cy: float
    w: float
    h: float
    score: float = 1.0
    tag: object = None


@dataclass
class Command:
    """Rates from -1 to 1. Pan above zero turns right, tilt above zero looks up, forward above zero moves ahead."""
    pan: float = 0.0
    tilt: float = 0.0
    forward: float = 0.0
    state: str = "idle"
    note: str = ""


@dataclass
class Settings:
    min_score: float = 0.4
    frames_to_confirm: int = 3  # sightings in a row before anything moves
    lost_after: float = 1.5  # seconds unseen before the target is given up
    search_seconds: float = 6.0  # how long to look toward where they went, then give up and stay still
    search_pan: float = 0.25
    stale_after: float = 0.6  # no frames for this long means the vision has failed, so stop
    pan_gain: float = 2.2
    tilt_gain: float = 1.2
    deadband: float = 0.04  # ignore tiny errors, so the head doesn't hunt
    max_pan: float = 1.0
    max_tilt: float = 0.5
    follow_height: float = 0.5  # box height to hold; a taller box means the person is closer
    stop_height: float = 0.62  # anyone this tall in the picture is too close to drive toward
    forward_gain: float = 1.5
    max_forward: float = 1.0
    search_if_off_centre: float = 0.2  # someone who vanished mid-picture is probably just hidden, so don't turn away
    turn_first: float = 0.22  # if they're this far off centre, turn before driving
    pan_slew: float = 4.0  # fastest change per second
    forward_slew: float = 1.5
    gate_base: float = 0.12  # how far a target may appear to jump between frames
    gate_per_second: float = 0.5
    max_size_change: float = 1.6


def _limit(value, low, high):
    return max(low, min(high, value))


def _toward(current, wanted, step):
    return current + _limit(wanted - current, -step, step)


class Tracker:
    """Stay with one person. Choosing the nearest-looking box each frame would jump to whoever walks past."""

    def __init__(self, settings):
        self.s = settings
        self.target = None
        self.velocity = (0.0, 0.0)
        self.last_seen = None
        self.sightings = 0

    def forget(self):
        self.target, self.velocity, self.last_seen, self.sightings = None, (0.0, 0.0), None, 0

    def predicted(self, now):
        elapsed = now - self.last_seen
        # Estimated speed isn't trusted for long, because people stop and turn.
        ahead = min(elapsed, 0.5)
        return self.target.cx + self.velocity[0] * ahead, self.target.cy + self.velocity[1] * ahead

    def update(self, boxes, now):
        boxes = [box for box in boxes if box.score >= self.s.min_score]
        if self.target is None:
            if boxes:
                self.target = max(boxes, key=lambda box: box.h)
                self.last_seen = now
                self.sightings = 1
            return self.target if boxes else None
        elapsed = max(now - self.last_seen, 1e-3)
        x, y = self.predicted(now)
        gate = self.s.gate_base + self.s.gate_per_second * elapsed
        best, best_cost = None, None
        for box in boxes:
            ratio = max(box.h / self.target.h, self.target.h / box.h)
            distance = abs(box.cx - x) + 0.5 * abs(box.cy - y)
            if ratio > self.s.max_size_change or distance > gate:
                continue
            cost = distance + 0.3 * (ratio - 1)
            if best is None or cost < best_cost:
                best, best_cost = box, cost
        if best is None:
            self.sightings = 0
            return None
        blend = 0.4
        self.velocity = tuple(
            (1 - blend) * old + blend * (new - previous) / elapsed
            for old, new, previous in zip(self.velocity, (best.cx, best.cy), (self.target.cx, self.target.cy))
        )
        self.target = best
        self.last_seen = now
        self.sightings += 1
        return best


class Follower:
    def __init__(self, settings=None):
        self.s = settings or Settings()
        self.tracker = Tracker(self.s)
        self.halted = False
        self.last_frame = None
        self.lost_at = None
        self.last_side = 0.0
        self.pan = self.tilt = self.forward = 0.0

    def halt(self):
        """Stop and stay stopped until resume(). Meant for a spoken "stop" or a physical button."""
        self.halted = True
        self.pan = self.tilt = self.forward = 0.0
        self.tracker.forget()

    def resume(self):
        self.halted = False
        self.lost_at = None

    def watchdog(self, now):
        """Call this on a timer, separately from frames. If the camera or detector dies, frames simply stop arriving."""
        if self.last_frame is not None and now - self.last_frame > self.s.stale_after:
            self.pan = self.tilt = self.forward = 0.0
            return Command(state="stale", note="no frames")
        return None

    def _stopped(self, state, note=""):
        self.pan = self.tilt = self.forward = 0.0
        return Command(state=state, note=note)

    def update(self, boxes, now):
        """Feed one frame's person boxes and get one command."""
        elapsed = now - self.last_frame if self.last_frame is not None else 0.0
        self.last_frame = now
        if self.halted:
            return self._stopped("halted")
        target = self.tracker.update(boxes, now)
        if target is None:
            return self._no_target(now, elapsed)
        self.lost_at = None
        if self.tracker.sightings < self.s.frames_to_confirm:
            return self._stopped("confirming")
        return self._steer(target, boxes, elapsed)

    def _no_target(self, now, elapsed):
        # Driving blind is never acceptable, so forward stops on the first frame without them.
        self.forward = 0.0
        if self.tracker.target is None:
            if self.lost_at is None:
                return self._stopped("idle")
        else:
            if now - self.tracker.last_seen < self.s.lost_after:
                # They may only be hidden for a moment. Hold still rather than swing away.
                self.pan = _toward(self.pan, 0.0, self.s.pan_slew * elapsed)
                self.tilt = 0.0
                return Command(self.pan, state="hidden", note="waiting")
            off_centre = self.tracker.target.cx - 0.5
            self.last_side = 0.0 if abs(off_centre) < self.s.search_if_off_centre else (1.0 if off_centre > 0 else -1.0)
            self.lost_at = self.tracker.last_seen + self.s.lost_after
            self.tracker.forget()
        searched = now - self.lost_at
        if searched < self.s.search_seconds:
            # Look toward where they went, then come back, so giving up leaves it facing the way it was.
            direction = self.last_side if searched < self.s.search_seconds / 2 else -self.last_side
            self.pan = _toward(self.pan, direction * self.s.search_pan, self.s.pan_slew * elapsed)
            self.tilt = 0.0
            return Command(self.pan, state="searching", note="looking where they went")
        self.lost_at = None
        return self._stopped("idle", "gave up looking")

    def _steer(self, target, boxes, elapsed):
        s = self.s
        x_error, y_error = target.cx - 0.5, 0.5 - target.cy
        wanted_pan = 0.0 if abs(x_error) < s.deadband else _limit(s.pan_gain * x_error, -s.max_pan, s.max_pan)
        wanted_tilt = 0.0 if abs(y_error) < s.deadband else _limit(s.tilt_gain * y_error, -s.max_tilt, s.max_tilt)
        tallest = max((box.h for box in boxes if box.score >= s.min_score), default=target.h)
        note = ""
        if tallest >= s.stop_height:
            wanted_forward, note = 0.0, "someone is too close"
        elif abs(x_error) > s.turn_first:
            wanted_forward, note = 0.0, "turning first"
        else:
            # Distance goes as one over box height, so this pulls just as hard when they're far away.
            wanted_forward = _limit(s.forward_gain * (1 / max(target.h, 0.02) - 1 / s.follow_height), 0.0, s.max_forward)
        self.pan = _toward(self.pan, wanted_pan, s.pan_slew * elapsed)
        self.tilt = _toward(self.tilt, wanted_tilt, s.pan_slew * elapsed)
        # Speeding up is gentle, but slowing down for someone too close happens at once.
        if wanted_forward < self.forward and note == "someone is too close":
            self.forward = 0.0
        else:
            self.forward = _toward(self.forward, wanted_forward, s.forward_slew * elapsed)
        return Command(self.pan, self.tilt, self.forward, "following", note)
