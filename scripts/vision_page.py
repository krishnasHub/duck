"""Vision Bench: boxes and steering from a camera, video file or test photo, in a local page.

Runs apart from the duck, with no language model. Frames are looked at and thrown away; nothing is saved.
Run with: uv run python scripts/vision_page.py, then open http://127.0.0.1:8767
"""
import argparse
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from common import ROOT
from detect import MODELS, Detector, describe
from follow import Box, Follower

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8767)
parser.add_argument("--model", default="yolox_nano", help="yolox_nano or yolox_tiny, in models/detector")
args = parser.parse_args()

HOST = "127.0.0.1"
ALLOWED_HOSTS = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
PAGE = ROOT / "web" / "vision.html"
TEST_PHOTO = MODELS / "street.jpg"
MAX_FRAME_BYTES = 5_000_000

detector = Detector(args.model)
follower = Follower()
lock = threading.Lock()


def person_boxes(found):
    return [Box((d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2, d.x2 - d.x1, d.y2 - d.y1, d.score) for d in found if d.label == "person"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def allowed(self):
        origin = self.headers.get("Origin")
        if self.headers.get("Host") in ALLOWED_HOSTS and (origin is None or urlparse(origin).netloc in ALLOWED_HOSTS):
            return True
        self.send_json(403, {"error": "local use only"})
        return False

    def send_json(self, status, payload):
        self.send_body(status, "application/json", json.dumps(payload).encode("utf-8"))

    def send_body(self, status, kind, body):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return
        path = urlparse(self.path).path
        if path == "/":
            self.send_body(200, "text/html; charset=utf-8", PAGE.read_bytes())
        elif path == "/test-photo" and TEST_PHOTO.exists():
            self.send_body(200, "image/jpeg", TEST_PHOTO.read_bytes())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length <= MAX_FRAME_BYTES else b""
        if self.path == "/api/see":
            self.see(body)
        elif self.path == "/api/halt":
            with lock:
                follower.halt()
            self.send_json(200, {"state": "halted"})
        elif self.path == "/api/resume":
            with lock:
                follower.resume()
            self.send_json(200, {"state": "idle"})
        else:
            self.send_json(404, {"error": "not found"})

    def see(self, body):
        try:
            image = Image.open(io.BytesIO(body)).convert("RGB")
        except (UnidentifiedImageError, OSError):
            self.send_json(400, {"error": "that frame isn't an image"})
            return
        started = time.perf_counter()
        found = detector.detect(image)
        detect_ms = (time.perf_counter() - started) * 1000
        with lock:
            command = follower.update(person_boxes(found), time.monotonic())
            target = follower.tracker.target
        self.send_json(200, {
            "boxes": [vars(item) for item in found],
            "sees": describe(found),
            "target": {"cx": target.cx, "cy": target.cy, "w": target.w, "h": target.h} if target else None,
            "command": vars(command),
            "detect_ms": round(detect_ms, 1),
        })


print(f"ready: http://{HOST}:{args.port}", flush=True)
ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
