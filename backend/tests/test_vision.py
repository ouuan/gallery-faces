from types import SimpleNamespace
import numpy as np
import pytest
from app import vision


def face(short=60):
    return np.array([0, 0, short, short]), vision.ARCFACE.copy(), short


@pytest.mark.parametrize(
    "initial,sizes",
    [
        ([], [640, 1280]),
        ([face(47.99)], [640, 1280]),
        ([face(48)], [640]),
        ([face(80)], [640]),
        ([face(80), face(20)], [640, 1280]),
    ],
)
@pytest.mark.parametrize("final", [[], [face(100)]])
def test_tiered_detection(monkeypatch, initial, sizes, final):
    original = np.zeros((200, 300, 3), dtype=np.uint8)
    monkeypatch.setattr(vision.cv2, "imread", lambda _: original)
    model = vision.Vision.__new__(vision.Vision)
    calls, features = [], []

    def detect(image, size):
        assert image is original
        calls.append(size)
        return initial if size == 640 else final

    model._detect = detect
    model._feature = lambda crop: features.append(crop) or b"feature"
    result = model.detect("unused")
    assert calls == sizes
    assert len(result) == len(features) == len(final if len(sizes) == 2 else initial)


def test_highres_failure_and_cancellation(monkeypatch):
    monkeypatch.setattr(
        vision.cv2, "imread", lambda _: np.zeros((200, 300, 3), dtype=np.uint8)
    )
    model = vision.Vision.__new__(vision.Vision)
    calls = []

    def detect(image, size):
        calls.append(size)
        if size == 1280:
            raise ValueError("inference failed")
        return [face(20)]

    model._detect = detect
    with pytest.raises(ValueError, match="inference failed"):
        model.detect("unused")
    assert calls == [640, 1280]
    calls.clear()
    with pytest.raises(ValueError):
        model.detect("unused", mode="highres")
    assert calls == [1280]
    calls.clear()
    with pytest.raises(vision.DetectionCancelled):
        model.detect("unused", cancel=lambda: bool(calls))
    assert calls == [640]


def test_decode_padding_nms_and_coordinates():
    model = vision.Vision.__new__(vision.Vision)
    outputs = []
    for channels in (1, 4, 10):
        for stride in (8, 16, 32):
            outputs.append(np.zeros(((640 // stride) ** 2 * 2, channels), np.float32))
    # Two identical anchors; NMS keeps one. A third box lies fully in padding.
    index = (10 * 80 + 10) * 2
    outputs[0][index : index + 2] = 0.9
    outputs[3][index : index + 2] = [2, 3, 4, 5]
    outputs[0][(60 * 80 + 10) * 2] = 0.9
    outputs[3][(60 * 80 + 10) * 2] = 1

    def run(_, inputs):
        tensor = inputs["input"]
        assert tensor.shape == (1, 3, 640, 640)
        np.testing.assert_allclose(
            tensor[0, :, 0, 0], (np.array([30, 20, 10]) - 127.5) / 128
        )
        assert np.all(tensor[:, :, 320:] == -127.5 / 128)
        return outputs

    model.detector = SimpleNamespace(
        run=run, get_inputs=lambda: [SimpleNamespace(name="input")]
    )
    image = np.full((160, 320, 3), [10, 20, 30], dtype=np.uint8)
    result = model._detect(image, 640)
    assert len(result) == 1
    box, points, short = result[0]
    np.testing.assert_allclose(box, [32, 28, 56, 60])
    np.testing.assert_allclose(points, np.full((5, 2), 40))
    assert short == 48


def test_recognition_rgb_normalization_and_alignment(monkeypatch):
    model = vision.Vision.__new__(vision.Vision)
    image = np.full((112, 112, 3), [10, 20, 30], dtype=np.uint8)
    monkeypatch.setattr(vision.cv2, "imread", lambda _: image)
    model._detect = lambda *_: [face()]

    def run(_, inputs):
        np.testing.assert_allclose(
            inputs["input"][0, :, 50, 50],
            (np.array([30, 20, 10]) - 127.5) / 127.5,
            atol=1e-7,
        )
        return [np.ones((1, 512), np.float32)]

    model.recognizer = SimpleNamespace(
        run=run, get_inputs=lambda: [SimpleNamespace(name="input")]
    )
    vector = np.frombuffer(model.detect("unused")[0][1], dtype=np.float32)
    assert vector.shape == (512,)
    assert np.linalg.norm(vector) == pytest.approx(1)


@pytest.mark.parametrize(
    "vector,version",
    [
        (np.zeros(512), vision.MODEL_VERSION),
        (np.ones(128), vision.MODEL_VERSION),
        (np.full(512, np.nan), vision.MODEL_VERSION),
        (np.ones(512), "old"),
    ],
)
def test_invalid_features(vector, version):
    with pytest.raises(ValueError):
        vision.validate_embedding(vector.astype(np.float32).tobytes(), version)


def test_checksum_cache_invalidates(tmp_path):
    import hashlib

    path = tmp_path / "model"
    path.write_bytes(b"valid")
    digest = hashlib.sha256(b"valid").hexdigest()
    vision.verify_model(path, digest)
    path.write_bytes(b"other")
    with pytest.raises(ValueError):
        vision.verify_model(path, digest)


@pytest.mark.parametrize(
    "value,expected", [("1", 1), ("8", 8), ("0", None), ("-1", None), ("bad", None)]
)
def test_concurrency_setting(monkeypatch, value, expected):
    from app.worker import worker_concurrency

    monkeypatch.setenv("WORKER_CONCURRENCY", value)
    if expected is None:
        with pytest.raises(ValueError):
            worker_concurrency()
    else:
        assert worker_concurrency() == expected


def test_concurrency_auto_affinity_and_quota(monkeypatch):
    from pathlib import Path
    from app import worker

    monkeypatch.setenv("WORKER_CONCURRENCY", "auto")
    monkeypatch.setattr(worker.os, "sched_getaffinity", lambda _: set(range(8)))

    def read(path):
        if str(path) == "/proc/self/cgroup":
            return "0::/container/child"
        if str(path) == "/sys/fs/cgroup/container/cpu.max":
            return "200000 100000"
        raise FileNotFoundError()

    monkeypatch.setattr(Path, "read_text", read)
    assert worker.worker_concurrency() == 2


def test_install_checksum_failure_preserves_existing(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setattr(vision, "DATA", tmp_path)
    monkeypatch.setattr(
        vision,
        "MODELS",
        {"test.onnx": ("test/model", hashlib.sha256(b"new").hexdigest())},
    )
    root = tmp_path / "models"
    root.mkdir()
    target = root / "test.onnx"
    target.write_bytes(b"old")

    def download(url, path):
        path.write_bytes(b"bad")

    monkeypatch.setattr(vision.urllib.request, "urlretrieve", download)
    with pytest.raises(ValueError):
        vision.install_models()
    assert target.read_bytes() == b"old"
    assert list(root.iterdir()) == [target]
    monkeypatch.setattr(
        vision.urllib.request, "urlretrieve", lambda url, path: path.write_bytes(b"new")
    )
    vision.install_models()
    assert target.read_bytes() == b"new"
    assert vision.models_ready()
    target.write_bytes(b"bad")
    assert not vision.models_ready()
