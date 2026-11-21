from types import SimpleNamespace
import numpy as np
import pytest
from app import vision


def face(short=60, x=0, y=0, score=0.9):
    return (
        np.array([x, y, x + short, y + short], dtype=np.float32),
        vision.ARCFACE.copy(),
        short,
        score,
    )


@pytest.mark.parametrize("allocator", ["supported", "missing_symbol", "unavailable"])
def test_idle_release_frees_sessions_and_reloads(monkeypatch, allocator):
    import weakref
    from concurrent.futures import ThreadPoolExecutor

    class Session:
        def __init__(self, *args, **kwargs):
            pass

    trims = []

    def trim(pad):
        trims.append(pad)
        return 1

    def libc(_):
        if allocator == "unavailable":
            raise OSError("unavailable")
        return SimpleNamespace(malloc_trim=trim) if allocator == "supported" else SimpleNamespace()

    monkeypatch.setattr(vision.ctypes, "CDLL", libc)
    monkeypatch.setattr(vision, "_sessions", {})
    monkeypatch.setattr(vision, "verify_model", lambda *_: (1, 2, 3, 4, 5))
    monkeypatch.setattr(vision.ort, "InferenceSession", Session)
    for _ in range(2):
        with ThreadPoolExecutor(max_workers=4) as pool:
            models = list(pool.map(lambda _: vision.Vision(), range(8)))
        assert all(model.detector is models[0].detector for model in models)
        assert all(model.recognizer is models[0].recognizer for model in models)
        refs = [weakref.ref(models[0].detector), weakref.ref(models[0].recognizer)]
        del models
        vision.release_idle_memory()
        assert all(ref() is None for ref in refs)
    assert trims == ([0, 0] if allocator == "supported" else [])


@pytest.mark.parametrize(
    "initial,sizes,expected_count",
    [
        ([], [640, 1280], None),
        ([face(47.99)], [640, 1280], None),
        ([face(48)], [640], 1),
        ([face(80)], [640], 1),
        ([face(80, x=0), face(20, x=200)], [640, 1280], None),
    ],
)
@pytest.mark.parametrize("final", [[], [face(100, x=400)]])
@pytest.mark.parametrize("threshold", [0.25, 0.5, 0.8])
def test_tiered_detection(monkeypatch, initial, sizes, expected_count, final, threshold):
    original = np.zeros((200, 300, 3), dtype=np.uint8)
    monkeypatch.setattr(vision.cv2, "imread", lambda _: original)
    model = vision.Vision.__new__(vision.Vision)
    calls, features = [], []

    def detect(image, size, actual_threshold):
        assert actual_threshold == threshold
        assert image is original
        calls.append(size)
        return initial if size == 640 else final

    model._detect = detect
    model._feature = lambda crop: features.append(crop) or b"feature"
    result = model.detect("unused", threshold=threshold)
    assert calls == sizes
    expected = (
        len(initial) + len(final) if expected_count is None else expected_count
    )
    assert len(result) == len(features) == expected


def test_multiscale_merge_deduplicates_and_preserves_distinct_faces(monkeypatch):
    original = np.zeros((400, 400, 3), dtype=np.uint8)
    monkeypatch.setattr(vision.cv2, "imread", lambda _: original)
    model = vision.Vision.__new__(vision.Vision)
    calls = []

    large_640 = face(180, x=10, y=10, score=0.92)
    shared_640 = face(30, x=250, y=250, score=0.65)
    shared_1280 = face(30, x=251, y=249, score=0.88)
    tiny_1280 = face(24, x=320, y=20, score=0.80)

    def detect(image, size, threshold):
        calls.append(size)
        return [large_640, shared_640] if size == 640 else [shared_1280, tiny_1280]

    model._detect = detect
    model._feature = lambda crop: b"feature"

    auto_result = model.detect("unused", mode="auto")
    assert calls == [640, 1280]
    assert len(auto_result) == 3
    # Higher-confidence 1280 box wins for the overlapping face; large 640 face and tiny 1280 face are both kept.
    xs = sorted(box[0] for box, _ in auto_result)
    assert xs == pytest.approx([10.0, 251.0, 320.0])

    calls.clear()
    highres_result = model.detect("unused", mode="highres")
    assert calls == [1280, 640]
    assert len(highres_result) == 3
    assert sorted(box[0] for box, _ in highres_result) == pytest.approx([10.0, 251.0, 320.0])


def test_highres_fallback_to_640_for_large_closeup(monkeypatch):
    original = np.zeros((1600, 1600, 3), dtype=np.uint8)
    monkeypatch.setattr(vision.cv2, "imread", lambda _: original)
    model = vision.Vision.__new__(vision.Vision)
    calls = []

    def detect(image, size, threshold):
        calls.append(size)
        return [] if size == 1280 else [face(600, x=500, y=300, score=0.95)]

    model._detect = detect
    model._feature = lambda crop: b"feature"
    result = model.detect("unused", mode="highres")
    assert calls == [1280, 640]
    assert len(result) == 1
    assert result[0][0] == pytest.approx([500.0, 300.0, 600.0, 600.0])


def test_highres_failure_and_cancellation(monkeypatch):
    monkeypatch.setattr(
        vision.cv2, "imread", lambda _: np.zeros((200, 300, 3), dtype=np.uint8)
    )
    model = vision.Vision.__new__(vision.Vision)
    calls = []

    def detect(image, size, threshold):
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
    calls.clear()
    model._detect = lambda image, size, threshold: calls.append(size) or [face(60)]
    with pytest.raises(vision.DetectionCancelled):
        model.detect("unused", mode="highres", cancel=lambda: bool(calls))
    assert calls == [1280]


@pytest.mark.parametrize(
    "size,height,width,rh,rw,ratio",
    [(640, 160, 320, 160, 320, 1), (1280, 960, 480, 960, 480, 1),
     (640, 1280, 640, 640, 320, 2)],
)
def test_decode_padding_nms_and_coordinates(size, height, width, rh, rw, ratio):
    model = vision.Vision.__new__(vision.Vision)
    outputs = []
    for channels in (1, 4, 10):
        for stride in (8, 16, 32):
            outputs.append(np.zeros(((size // stride) ** 2 * 2, channels), np.float32))
    # Two identical anchors; NMS keeps one. A third box lies fully in padding.
    index = (10 * (size // 8) + 10) * 2
    outputs[0][index : index + 2] = 0.9
    outputs[3][index : index + 2] = [2, 3, 4, 5]
    outputs[0][-1] = 0.9
    outputs[3][-1] = 1

    def run(_, inputs):
        tensor = inputs["input"]
        assert tensor.shape == (1, 3, size, size)
        np.testing.assert_allclose(
            tensor[0, :, rh - 1, rw - 1], (np.array([30, 20, 10]) - 127.5) / 128
        )
        assert np.all(tensor[:, :, rh:] == -127.5 / 128)
        assert np.all(tensor[:, :, :, rw:] == -127.5 / 128)
        return outputs

    model.detector = SimpleNamespace(
        run=run, get_inputs=lambda: [SimpleNamespace(name="input")]
    )
    image = np.full((height, width, 3), [10, 20, 30], dtype=np.uint8)
    result = model._detect(image, size)
    assert len(result) == 1
    box, points, short, score = result[0]
    np.testing.assert_allclose(box, np.array([64, 56, 112, 120]) * ratio)
    np.testing.assert_allclose(points, np.full((5, 2), 80 * ratio))
    assert short == 48
    assert score == pytest.approx(0.9)
    assert model._detect(image, size, threshold=0.95) == []
    outputs[0][index : index + 2] = 0.3
    assert model._detect(image, size) == []
    assert len(model._detect(image, size, threshold=0.3)) == 1


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
