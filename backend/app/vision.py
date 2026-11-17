import hashlib
import os
import tempfile
import threading
import urllib.request

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image
from skimage.metrics import structural_similarity
from skimage.transform import SimilarityTransform
from threadpoolctl import threadpool_limits
from .db import DATA

MODEL_VERSION = "scrfd-10g-kps+r50-webface600k-d0971591"
MODEL_COMMIT = "d09715916a0778919a770c343533641e250b8699"
MODELS = {
    "scrfd.onnx": (
        "detection/model.onnx",
        "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
    ),
    "r50.onnx": (
        "recognition/model.onnx",
        "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
    ),
}
ARCFACE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
_lock = threading.RLock()
_verified = {}
_sessions = {}
# Set once per process, never enter/leave a global BLAS limit inside worker threads.
cv2.setNumThreads(1)
_thread_limit = threadpool_limits(limits=1)


def file_state(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def verify_model(path, digest):
    with _lock:
        try:
            state = file_state(path)
            if _verified.get((path, digest)) == state:
                return state
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual == digest and file_state(path) == state:
                _verified[path, digest] = state
                return state
        except OSError:
            pass
        raise ValueError(
            "模型未安装或校验失败，请运行 python -m app.worker --install-models"
        )


def models_ready():
    try:
        for name, (_, digest) in MODELS.items():
            verify_model(DATA / "models" / name, digest)
        return True
    except ValueError:
        return False


def install_models():
    root = DATA / "models"
    root.mkdir(parents=True, exist_ok=True)
    for name, (remote, digest) in MODELS.items():
        path = root / name
        try:
            verify_model(path, digest)
            continue
        except ValueError:
            pass
        fd, temporary = tempfile.mkstemp(dir=root, suffix=".download")
        os.close(fd)
        from pathlib import Path

        temporary = Path(temporary)
        try:
            urllib.request.urlretrieve(
                f"https://huggingface.co/immich-app/buffalo_l/resolve/{MODEL_COMMIT}/{remote}",
                temporary,
            )
            verify_model(temporary, digest)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def validate_embedding(value, version=MODEL_VERSION):
    if version != MODEL_VERSION:
        raise ValueError("人脸特征版本不兼容，请重新检测或上传参考图")
    vector = np.frombuffer(value, dtype=np.float32)
    norm = np.linalg.norm(vector.astype(np.float64))
    if (
        vector.shape != (512,)
        or not np.isfinite(vector).all()
        or not np.isfinite(norm)
        or norm < 1e-12
        or norm > np.finfo(np.float32).max
    ):
        raise ValueError("无效人脸特征")
    return vector


class DetectionCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel and cancel():
        raise DetectionCancelled()


def nms(boxes, scores):
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        i, rest = order[0], order[1:]
        keep.append(i)
        intersection = np.maximum(
            0,
            np.minimum(boxes[i, 2:], boxes[rest, 2:])
            - np.maximum(boxes[i, :2], boxes[rest, :2]),
        ).prod(axis=1)
        area = (boxes[:, 2:] - boxes[:, :2]).prod(axis=1)
        iou = intersection / np.maximum(area[i] + area[rest] - intersection, 1e-12)
        order = rest[iou <= 0.4]
    return keep


class Vision:
    def __init__(self):
        with _lock:
            for name, (_, digest) in MODELS.items():
                path = DATA / "models" / name
                state = verify_model(path, digest)
                key = (path, state)
                if key not in _sessions:
                    options = ort.SessionOptions()
                    options.intra_op_num_threads = options.inter_op_num_threads = 1
                    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                    _sessions[key] = ort.InferenceSession(
                        str(path),
                        sess_options=options,
                        providers=["CPUExecutionProvider"],
                    )
                setattr(
                    self,
                    "detector" if name == "scrfd.onnx" else "recognizer",
                    _sessions[key],
                )

    def _detect(self, image, size):
        height, width = image.shape[:2]
        scale = size / max(height, width)
        rw, rh = max(1, int(width * scale)), max(1, int(height * scale))
        padded = np.zeros((size, size, 3), dtype=np.uint8)
        padded[:rh, :rw] = cv2.resize(image, (rw, rh))
        blob = cv2.dnn.blobFromImage(
            padded, 1 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True
        )
        outputs = self.detector.run(None, {self.detector.get_inputs()[0].name: blob})
        boxes, points, scores = [], [], []
        for level, stride in enumerate((8, 16, 32)):
            score = outputs[level].reshape(-1)
            distances = outputs[level + 3].reshape(-1, 4) * stride
            landmarks = outputs[level + 6].reshape(-1, 5, 2) * stride
            centers = (
                np.stack(
                    np.mgrid[: size // stride, : size // stride][::-1], axis=-1
                ).reshape(-1, 2)
                * stride
            )
            centers = np.repeat(centers, 2, axis=0)
            ids = np.flatnonzero(score >= 0.5)
            boxes.append(
                np.concatenate(
                    [
                        centers[ids] - distances[ids, :2],
                        centers[ids] + distances[ids, 2:],
                    ],
                    axis=1,
                )
            )
            points.append(landmarks[ids] + centers[ids, None, :])
            scores.append(score[ids])
        boxes, points, scores = (
            np.concatenate(boxes),
            np.concatenate(points),
            np.concatenate(scores),
        )
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, rw)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, rh)
        valid = (
            np.isfinite(boxes).all(axis=1)
            & np.isfinite(points).all(axis=(1, 2))
            & np.isfinite(scores)
            & ((boxes[:, 2:] - boxes[:, :2]) > 0).all(axis=1)
        )
        boxes, points, scores = boxes[valid], points[valid], scores[valid]
        keep = nms(boxes, scores)
        # Return original coordinates and the effective short side in model coordinates.
        ratios = np.array([rw / width, rh / height], dtype=np.float32)
        return [
            (box / np.tile(ratios, 2), point / ratios, min(box[2:] - box[:2]))
            for box, point in zip(boxes[keep], points[keep])
        ]

    def _feature(self, crop):
        blob = cv2.dnn.blobFromImage(
            crop, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True
        )
        vector = (
            self.recognizer.run(None, {self.recognizer.get_inputs()[0].name: blob})[0]
            .astype(np.float32)
            .reshape(-1)
        )
        validate_embedding(vector.tobytes())
        return (vector / np.linalg.norm(vector)).astype(np.float32).tobytes()

    def detect(self, path, mode="auto", cancel=None):
        if mode not in ("auto", "highres"):
            raise ValueError("无效检测模式")
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("无法读取图片")
        check_cancel(cancel)
        faces = self._detect(image, 1280 if mode == "highres" else 640)
        if mode == "auto" and (not faces or any(face[2] < 48 for face in faces)):
            check_cancel(cancel)
            faces = self._detect(image, 1280)
        result = []
        for box, points, _ in faces:
            check_cancel(cancel)
            transform = SimilarityTransform.from_estimate(points, ARCFACE)
            if not transform:
                raise ValueError("无法对齐人脸")
            crop = cv2.warpAffine(
                image, transform.params[:2], (112, 112), borderValue=0
            )
            x, y, right, bottom = box
            result.append(
                (
                    [float(x), float(y), float(right - x), float(bottom - y)],
                    self._feature(crop),
                )
            )
        check_cancel(cancel)
        return result

    def crop_feature(self, path, box):
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("无法读取图片")
        x, y, w, h = map(int, box)
        crop = image[max(0, y) : max(0, y + h), max(0, x) : max(0, x + w)]
        if not crop.size:
            raise ValueError("无效人脸区域")
        return self._feature(cv2.resize(crop, (112, 112)))


def phash(path):
    with Image.open(path) as im:
        a = np.asarray(im.convert("L").resize((32, 32)), dtype=np.float32)
    low = cv2.dct(a)[:8, :8].flatten()
    bits = low > np.median(low[1:])
    return f"{sum(int(bit) << i for i, bit in enumerate(bits)):016x}"


def similarity(a, b):
    with Image.open(a) as im:
        aa = np.asarray(im.convert("L").resize((256, 256)))
    with Image.open(b) as im:
        bb = np.asarray(im.convert("L").resize((256, 256)))
    return float(structural_similarity(aa, bb, data_range=255))


def candidates(embedding, references):
    vector = validate_embedding(embedding)
    scores = {}
    for ref in references:
        v = validate_embedding(
            ref["embedding"],
            ref["model_version"] if "model_version" in ref.keys() else MODEL_VERSION,
        )
        score = float(np.dot(vector, v) / (np.linalg.norm(vector) * np.linalg.norm(v)))
        scores[ref["person_id"]] = max(scores.get(ref["person_id"], -1), score)
    return [
        {"person_id": person, "score": score}
        for person, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[
            :5
        ]
    ]
