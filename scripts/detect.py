"""Find objects in an image with YOLOX, a small detector under the Apache 2.0 licence.

Runs through ONNX Runtime on whatever it finds, which can be the GPU on the Jetson. Knows 80 everyday things (COCO),
including people. It names things and boxes them; it doesn't understand a scene.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import onnxruntime
from PIL import Image

from common import ROOT

MODELS = ROOT / "models" / "detector"
STRIDES = (8, 16, 32)
PAD_VALUE = 114.0
NAMES = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign parking_meter bench bird cat dog "
    "horse sheep cow elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee skis snowboard sports_ball kite "
    "baseball_bat baseball_glove skateboard surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich "
    "orange broccoli carrot hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv laptop mouse remote keyboard "
    "cell_phone microwave oven toaster sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush"
).split()


@dataclass
class Detection:
    """A box, with coordinates as fractions of the image so nothing depends on camera resolution."""
    label: str
    score: float
    x1: float
    y1: float
    x2: float
    y2: float


class Detector:
    def __init__(self, model="yolox_nano", threads=None):
        options = onnxruntime.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        wanted = [name for name in ("CUDAExecutionProvider", "CPUExecutionProvider") if name in onnxruntime.get_available_providers()]
        self.session = onnxruntime.InferenceSession(str(MODELS / f"{model}.onnx"), options, providers=wanted)
        shape = self.session.get_inputs()[0].shape
        self.height, self.width = int(shape[2]), int(shape[3])
        self.input_name = self.session.get_inputs()[0].name
        grids, strides = [], []
        for stride in STRIDES:
            rows, columns = self.height // stride, self.width // stride
            x, y = np.meshgrid(np.arange(columns), np.arange(rows))
            grids.append(np.stack((x, y), 2).reshape(-1, 2))
            strides.append(np.full((rows * columns, 1), stride))
        self.grid = np.concatenate(grids).astype(np.float32)
        self.stride = np.concatenate(strides).astype(np.float32)

    def _prepare(self, image):
        """Fit the image into the model's square, top-left, padded with grey, in the blue-green-red order it was trained on."""
        ratio = min(self.width / image.width, self.height / image.height)
        size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        pixels = np.asarray(image.convert("RGB").resize(size, Image.BILINEAR), dtype=np.float32)[:, :, ::-1]
        canvas = np.full((self.height, self.width, 3), PAD_VALUE, dtype=np.float32)
        canvas[: size[1], : size[0]] = pixels
        return canvas.transpose(2, 0, 1)[None], ratio

    def detect(self, image, threshold=0.35, overlap=0.5, labels=None):
        tensor, ratio = self._prepare(image)
        raw = self.session.run(None, {self.input_name: tensor})[0][0]
        centres = (raw[:, :2] + self.grid) * self.stride
        sizes = np.exp(raw[:, 2:4]) * self.stride
        scores = raw[:, 4:5] * raw[:, 5:]
        classes = scores.argmax(1)
        best = scores[np.arange(len(scores)), classes]
        keep = best >= threshold
        if labels:
            wanted = [NAMES.index(label) for label in labels]
            keep &= np.isin(classes, wanted)
        centres, sizes, classes, best = centres[keep], sizes[keep], classes[keep], best[keep]
        boxes = np.concatenate((centres - sizes / 2, centres + sizes / 2), 1) / ratio
        scale = np.array([image.width, image.height, image.width, image.height], dtype=np.float32)
        boxes = np.clip(boxes / scale, 0, 1)
        found = []
        for index in _non_max_suppression(boxes, best, classes, overlap):
            x1, y1, x2, y2 = boxes[index]
            found.append(Detection(NAMES[classes[index]], float(best[index]), float(x1), float(y1), float(x2), float(y2)))
        return found


def _non_max_suppression(boxes, scores, classes, overlap):
    """Keep the best box where several cover the same object. Shifting each class apart stops them suppressing each other."""
    if not len(boxes):
        return []
    shifted = boxes + classes[:, None] * 2.0
    order = scores.argsort()[::-1]
    areas = (shifted[:, 2] - shifted[:, 0]) * (shifted[:, 3] - shifted[:, 1])
    kept = []
    while len(order):
        top, rest = order[0], order[1:]
        kept.append(int(top))
        low = np.maximum(shifted[top, :2], shifted[rest, :2])
        high = np.minimum(shifted[top, 2:], shifted[rest, 2:])
        common = np.prod(np.clip(high - low, 0, None), axis=1)
        order = rest[common / (areas[top] + areas[rest] - common + 1e-9) <= overlap]
    return kept


def describe(found):
    """A short line the Ring could be handed, so he can talk about what he sees."""
    if not found:
        return "nothing I recognise"
    parts = []
    for label, count in Counter(item.label.replace("_", " ") for item in found).most_common(4):
        if count == 1:
            parts.append(f"{'an' if label[0] in 'aeiou' else 'a'} {label}")
        else:
            parts.append(f"{count} {'people' if label == 'person' else label + 's'}")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
