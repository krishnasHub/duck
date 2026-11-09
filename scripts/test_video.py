"""The real detector and follow logic on recorded video, with a moving crop standing in for a camera that can turn.

No webcam needed. Any phone clip works: pass its path. There's no ground truth, so the numbers only flag trouble,
and the contact sheet (--sheet) is what shows whether it stayed with the same person. Nothing is saved unless asked.
"""
import argparse
import statistics
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from detect import MODELS, Detector
from follow import Box, Follower, Settings
from look import signature

CLIPS = MODELS / "clips"
VIEW = 0.6
PAN_SPEED = 0.25
WIDTH = 640
# A jump this far between frames, in fractions of the whole picture per second, is faster than a walker crosses the view.
JUMP_PER_SECOND = 0.6
SHEET_COLUMNS = 6
SHEET_ROWS = 4
THUMB_WIDTH = 260


def frames(path, fps):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split(",")[:2])
    height = WIDTH * height // width // 2 * 2
    size = WIDTH * height * 3
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={WIDTH}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    while True:
        data = process.stdout.read(size)
        if len(data) < size:
            break
        yield Image.frombytes("RGB", (WIDTH, height), data)
    process.wait()


def people(found, view, use_looks):
    hsv = np.asarray(view.convert("HSV")) if use_looks else None
    return [
        Box((d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2, d.x2 - d.x1, d.y2 - d.y1, d.score,
            look=signature(hsv, (d.x1, d.y1, d.x2, d.y2)) if use_looks else None)
        for d in found if d.label == "person"
    ]


def run(path, detector, fps, sheet_path=None, use_looks=True, enroll=False, min_look=None):
    follower = Follower(Settings(min_look=min_look) if min_look else None)
    pan = 0.5
    states, off, jumps, shots = [], [], [], []
    last = None
    all_frames = list(frames(path, fps))
    every = max(1, len(all_frames) // (SHEET_COLUMNS * SHEET_ROWS))
    for index, frame in enumerate(all_frames):
        seen = frame.width * VIEW
        left = pan * (frame.width - seen)
        view = frame.crop((int(left), 0, int(left + seen), frame.height))
        command = follower.update(people(detector.detect(view), view, use_looks), index / fps)
        states.append(command.state)
        # Stands in for the owner pressing "this is me" once it has them: the first person it confirms.
        if enroll and command.state == "following" and follower.tracker.owner is None:
            follower.enroll()
        target = follower.tracker.target
        place = None
        if target and command.state == "following":
            off.append(abs(target.cx - 0.5))
            place = (left + target.cx * seen) / frame.width
            if last is not None and abs(place - last[0]) > JUMP_PER_SECOND * (index - last[1]) / fps + 0.05:
                jumps.append(round(index / fps, 1))
            last = (place, index)
        if sheet_path and index % every == 0:
            shot = frame.copy()
            draw = ImageDraw.Draw(shot)
            draw.rectangle((left, 0, left + seen, frame.height - 1), outline=(255, 255, 0), width=2)
            if place is not None:
                x = place * frame.width
                y = target.cy * frame.height
                half_w = target.w * seen / 2
                half_h = target.h * frame.height / 2
                draw.rectangle((x - half_w, y - half_h, x + half_w, y + half_h), outline=(255, 0, 0), width=4)
            draw.text((6, 6), f"{index / fps:.1f}s {command.state}", fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
            shots.append(shot)
        pan = max(0.0, min(1.0, pan + command.pan * PAN_SPEED / fps))
    if sheet_path and shots:
        height = shots[0].height * THUMB_WIDTH // shots[0].width
        rows = (len(shots) + SHEET_COLUMNS - 1) // SHEET_COLUMNS
        sheet = Image.new("RGB", (THUMB_WIDTH * SHEET_COLUMNS, height * rows))
        for number, shot in enumerate(shots):
            sheet.paste(shot.resize((THUMB_WIDTH, height)), (number % SHEET_COLUMNS * THUMB_WIDTH, number // SHEET_COLUMNS * height))
        sheet.save(sheet_path)
    following = states.count("following")
    print(f"{path.name}: {len(states)} frames at {fps}/s, following on {following} ({following / max(1, len(states)):.0%}), "
          f"median off centre {statistics.median(off) if off else float('nan'):.3f}, sudden jumps at {jumps or 'none'} s")
    print(f"  states: { {state: states.count(state) for state in sorted(set(states))} }")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("clips", nargs="*", type=Path)
    parser.add_argument("--fps", type=int, nargs="*", default=[10, 3])
    parser.add_argument("--sheet", type=Path, help="Folder for contact sheets. Yellow is the view, red is who it's following.")
    parser.add_argument("--model", default="yolox_nano")
    parser.add_argument("--no-looks", action="store_true", help="Track by position alone, as it did before.")
    parser.add_argument("--enroll", action="store_true", help="Follow only the first person it confirms.")
    parser.add_argument("--tag", default="", help="Added to contact sheet names.")
    parser.add_argument("--min-look", type=float)
    args = parser.parse_args()
    clips = args.clips or sorted(CLIPS.glob("*"))
    detector = Detector(args.model, threads=4)
    for clip in clips:
        for fps in args.fps:
            sheet = args.sheet / f"{clip.stem}_{fps}fps{args.tag}.jpg" if args.sheet else None
            run(clip, detector, fps, sheet, not args.no_looks, args.enroll, args.min_look)


if __name__ == "__main__":
    main()
