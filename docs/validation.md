# Validation record

Verification passed on Python 3.14.10, OpenCV 5.0.0, Node 26 and the current pinned frontend dependencies. Twenty-nine backend tests, six unit tests and nine Chromium workflow tests passed; the production frontend build passed.

The implementation is tested with an isolated temporary data directory. No demonstration photographs, models, cookies, passwords or runtime database are committed.

- Backend workflow coverage: transactional group saves and rollback, concurrent group creation, queue deduplication, running reference changes, concurrent manual edits, no-face defaults, access control, same-source publisher/date matching, same-member all-person matching, stable cursors, source text backfill, original bytes, explicit batch scope and split memory.
- Person workflow coverage: atomic create-from-face with groups, accounts, optional reference and rollback, multi-select confirmed references with ownership checks and deduplication, revision conflicts, manual faces without embeddings, deletion preserving images and groups, candidate/undo cleanup, and deletion during a running rematch.
- Real-API browser checks for the person actions: cancel without creating, retry after a failed save, create and confirm with a group, account and reference, multi-select confirmed references and cancel without saving, create from a manual face, cancel/confirm deletion, retained photos, and mobile/dark layouts.
- Publisher coverage: nickname import/backfill and schema migration, person filters across platforms with case-insensitive account matching and same-source dates, display-name priority, URL restoration, single-source link suppression, and uppercase X labels.
- Reference avatar coverage: selected-face crop dimensions and pixels, uploaded multi-face selection, legacy box recovery/cache, avatar replacement after reference deletion, private crop access, filter rows without avatars, and desktop/mobile placeholders for missing references.
- Recycle-bin coverage: whole duplicate-group expansion beyond 500 members, scope-token conflicts, atomic processing conflicts, thumbnail/review preservation, reference suspension, migration, pagination, cleanup retry, no resurrection by ordinary import, pre-request download skipping, hash-verified selective restore, cancellation and browser error recovery.
- Cascader coverage: grouped and ungrouped people, overlapping memberships, deduplicated selections and synchronized deselection, search, URL restoration, any/all matching, mobile draft/apply and popup viewport bounds.
- Manual face box coverage: mouse and touch drawing, reverse drags, scaling to original pixels, clamping at image edges, ignoring clicks, cancel/Escape, pointer cancellation, clearing drafts on image changes and retaining drafts after failed saves. Coordinates have no manual input entry.
- Review queue coverage: default union includes unknown/automatic unconfirmed faces, no detections, failed/pending detection and incomplete sources; excludes hidden images and completed manual decisions; confirmed items leave the queue, with other categories still available.
- Frontend unit coverage: filter URL round-trip/defaults and plain-text source rendering with safe links.
- Site title coverage: saved values persist across reloads, appear for logged-out visitors and on the login screen, fit mobile headers, reject blank/oversized input, and survive updates from clients omitting the title field.
- Chromium browser coverage: mobile filter application/restoration, person creation and cancelled group creation, focus behavior, viewport overflow at 390/1280/1440 pixels and light/dark captures.
- Current model checks and throughput results are recorded below. The previous YuNet/SFace smoke measurements no longer describe the deployed pipeline.
- Full backup/restore round trip preserved both SQLite data and asset bytes and passed integrity checks. Docker Compose configuration validates.

Real X metadata checks reproduced empty gallery-dl content for three posts with nonempty details.full_text. The compatibility entry point fetched all three captions successfully (76/134/174 characters), and missing database/sidecar captions were backfilled. This metadata-only check did not download media again.

External validation still requires user infrastructure: broader Instagram/X download coverage with valid user cookies, representative recognition/deduplication accuracy, large-library performance, and representative deployment load testing. The pinned downloader can require a deliberate version upgrade when platforms change.

## SCRFD/R50 validation (2026-11-17)

The full backend suite passes (101 tests), including tier boundaries, final-result replacement, highres upload, task upgrades/append/retry, cancellation before writes, concurrent slots and per-image ordering, failure isolation, restart recovery, cgroup/affinity configuration, reference-version races, human revisions, invalid/old feature rejection, decoding, NMS, RGB normalization and five-point alignment. The production Docker build (including frontend type checking/build) and Compose configuration pass.

Both downloaded FP32 weights pass the pinned SHA-256 checks. Real CPU inference at 640 and 1280 detects the skimage astronaut fixture. Recognition produces finite float32 512-dimensional unit vectors. Shared-session concurrent mixed-size boxes/features match serial outputs (absolute tolerances 1e-5 / 1e-6).

Reproduce with installed models using `DATA_DIR=/path/to/data PYTHONPATH=backend backend/.venv/bin/python scripts/validation/vision_benchmark.py`. The batch comprises the skimage astronaut, a 256-pixel version placed on a 1024-pixel black canvas, and a blank image. Two of three auto inputs trigger the second pass (66.7%); 640 and final-auto face counts are both 1/1/0. Each measured batch runs 24 jobs, alternating auto/highres, after warmup. No user photographs or model binaries are committed.

| Compute slots | Wall seconds | Images/s | CPU seconds | CPU utilization (one core = 100%) | Process peak RSS MiB |
| --- | --- | --- | --- | --- | --- |
| 1 | 29.95 | 0.80 | 29.55 | 98.7% | 746 |
| 4 | 8.19 | 2.93 | 30.35 | 370.5% | 1295 |

RSS is the process high-water mark, with the concurrent pass following the serial pass in the same process. These synthetic fixtures verify execution and concurrency, not recognition quality or production throughput. Initial thresholds still need evaluation on representative gallery photos. The pinned detector has static 640 output-shape annotations despite supporting dynamic spatial inputs; ONNX Runtime logs output-shape warnings at 1280, but returns the expected stride-specific tensor lengths, validated by real inference and equivalence checks. Existing Starlette TestClient emits one unrelated httpx deprecation warning.

## Worker idle reclamation (2026-11-18)

All 231 backend tests and Docker Compose configuration validation pass. Idle-policy tests use a controlled monotonic clock to cover timeout boundaries, arrivals before/at the deadline, all four task kinds, long-running jobs, one release per idle period, resumption, disabled/invalid configuration and shutdown. Model lifecycle tests verify session collection and shared lazy reload, including platforms without malloc_trim.

Real-model validation on local Linux/Python 3.14.10 retained a four-thread executor across three rounds. Each round ran 12 mixed auto/highres jobs using the astronaut, small astronaut and blank fixtures described above, then called release_idle_memory after all jobs finished. Reloaded boxes and embeddings matched the first round at absolute tolerances 1e-5 and 1e-6. Current RSS was read from /proc/self/status, rather than the process high-water mark.

| Round | RSS before release MiB | RSS after release MiB | Release seconds |
| --- | --- | --- | --- |
| 1 | 1137.9 | 176.0 | 0.068 |
| 2 | 1290.3 | 201.2 | 0.041 |
| 3 | 1174.5 | 162.9 | 0.032 |

These measurements are workload- and allocator-dependent observations, not fixed memory limits or unit-test thresholds. The API process has its own model cache and is not included in these figures.

## Duplicate-group review (2026-11-18)

The full backend suite passes (287 tests), including 15 new representative-review cases. The 24 frontend unit tests, production build and 31 targeted Chromium workflow tests pass. Group-review captures were inspected at 390/1280 pixels in light and dark themes, with no horizontal overflow.

Coverage includes selection before filtering and the 500-group limit, groups with 507 members, original-byte-size ties, member deep links, per-image result preservation, automatic merge after importing a larger copy, both split directions, selective restore, source/post deduplication, group feedback pagination and hidden-member exclusion. Public identity and no-face filters use the displayed representative, including fallback while a larger member is pending, failed or missing provenance. Stale representative mutations return 409; batch failures preserve successful edits and unsaved choices.

A browser smoke test against the real API and an isolated temporary database verified a member link opening its representative, feedback attached to a smaller member appearing in the group, representative confirmation plus feedback resolution removing the group from review, and splitting the smaller member restoring its own unresolved review state. Temporary fixture images and databases are not committed.
