"""Run with backend Python and PYTHONPATH=backend; DATA_DIR must contain installed models.
Uses skimage's astronaut fixture, not user photos. Assets remain in a temporary directory.
"""

import json
import resource
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from skimage import data
from app.vision import Vision, MODEL_VERSION, validate_embedding
from app.worker import worker_concurrency


def main():
    model = Vision()
    astronaut = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    small = np.zeros((1024, 1024, 3), np.uint8)
    small[400:656, 400:656] = cv2.resize(astronaut, (256, 256))
    fixtures = [astronaut, small, np.zeros((768, 1024, 3), np.uint8)]
    with tempfile.TemporaryDirectory(prefix="gallery-vision-benchmark-") as directory:
        paths = []
        for i, image in enumerate(fixtures):
            path = Path(directory) / f"{i}.png"
            cv2.imwrite(str(path), image)
            paths.append(path)
        detections = {size: model._detect(astronaut, size) for size in (640, 1280)}
        assert all(detections.values())
        jobs = [
            (path, mode)
            for _ in range(4)
            for path in paths
            for mode in ("auto", "highres")
        ]

        def run(job):
            return model.detect(job[0], mode=job[1])

        # Warm both input sizes and recognition before measuring.
        for path in paths:
            for mode in ("auto", "highres"):
                run((path, mode))
        reports, outputs = [], []
        for slots in (1, worker_concurrency()):
            wall, cpu = time.perf_counter(), time.process_time()
            with ThreadPoolExecutor(max_workers=slots) as pool:
                result = list(pool.map(run, jobs))
            elapsed, cpu_seconds = time.perf_counter() - wall, time.process_time() - cpu
            reports.append(
                {
                    "slots": slots,
                    "jobs": len(jobs),
                    "seconds": elapsed,
                    "images_per_second": len(jobs) / elapsed,
                    "cpu_seconds": cpu_seconds,
                    "cpu_percent_one_core": 100 * cpu_seconds / elapsed,
                    "process_peak_rss_mib": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss
                    / 1024,
                }
            )
            outputs.append(result)
        for serial, parallel in zip(*outputs):
            assert len(serial) == len(parallel)
            for (box, embedding), (other_box, other_embedding) in zip(serial, parallel):
                np.testing.assert_allclose(box, other_box, atol=1e-5)
                vector = validate_embedding(embedding)
                assert np.linalg.norm(vector) > 0.99999
                np.testing.assert_allclose(
                    vector, validate_embedding(other_embedding), atol=1e-6
                )
        initial = [model._detect(image, 640) for image in fixtures]
        retries = sum(
            not faces or any(face[2] < 48 for face in faces) for faces in initial
        )
        print(
            json.dumps(
                {
                    "model": MODEL_VERSION,
                    "fixtures": ["astronaut", "small astronaut on black", "blank"],
                    "retry_fraction": retries / len(fixtures),
                    "640_face_counts": [len(f) for f in initial],
                    "final_auto_face_counts": [len(run((p, "auto"))) for p in paths],
                    "mixed_size_equivalence": True,
                    "measurements": reports,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
