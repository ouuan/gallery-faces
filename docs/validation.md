# Validation record

## Indexed group queries (schema v14)

A local copy of a v13 snapshot (42,712 images, 23,525 posts, 98,128 faces, 151 people) was migrated and compared with the previous API. All 78 public cases, 159 admin cases and 88 randomized requests/continuations matched the reference JSON, including counts, order, cursors and source details. For six history pages that exceeded the old 2.5 s benchmark cutoff, the reference was the verified decision-first query. These measurements are local HTTP response times, not production latency.

| Three-run median | v13 | v14 |
| --- | ---: | ---: |
| Default gallery, exact count | 184 ms | 10 ms |
| Two-group exact person match, gallery / posts | 242 / 268 ms | 7 / 6 ms |
| All 151 people, gallery `subset` / posts `any` | 303 / 6 ms | 55 / 8 ms |
| Default review queue, first / last page | 153 / 312 ms | 16 / 12 ms |
| Duplicate decision history, first and last pages | >2.5 s | 14–26 ms |
| Reference change, 12,820 images, empty / existing queue | 435 / 290 ms | 255 / 178 ms |

With one CPU and eight concurrent requests, all 24 requests finished in each of three mixed read batches (P95 194–219 ms) at the unchanged two-second public SQL budget. The one-second public lock wait is separate. On a disposable copy, changing image sizes in 1, 32 and 256 groups took 4.3, 5.5 and 17.8 ms respectively, including connection, group refresh and commit (five-run medians). Single-face save and undo were about 10 ms each. No production requests or data changes were needed for these checks.

## Large-library request benchmark

From the repository root, with backend development dependencies installed, run:

```sh
PYTHONPATH=backend backend/.venv/bin/python scripts/validation/library_queries.py
```

This builds temporary 10,000- and 50,000-image databases, including duplicate groups, reference faces, and trashed images. It measures complete in-process HTTP responses (three-run medians), then traces business SQL reads separately and reports uncompressed response bytes. It includes cursor pages, a sparse publisher and a dataset with every post at the same timestamp. No image processing, network, or existing gallery data is involved. Use `--sizes` and `--repeats` to change the workload. Regression tests assert response equivalence and bounded SQL counts, not hardware-dependent timings.

Reference run at 50,000 images: posts first/next page 4.7/4.1 ms, gallery first/next page 115/15 ms, sparse-publisher gallery continuation 16 ms, and all-dates-tied gallery continuation 13 ms. Page reads for recognition review, trash and duplicate review used 5, 8 and 6 business queries respectively; listing 500 people used 4. The default gallery first page still includes an exact count.

Verification passed on Python 3.14.10, OpenCV 5.0.0, Node 26 and the current pinned frontend dependencies. Twenty-nine backend tests, six unit tests and nine Chromium workflow tests passed; the production frontend build passed.

The implementation is tested with an isolated temporary data directory. No demonstration photographs, models, cookies, passwords or runtime database are committed.

- Backend workflow coverage: transactional group saves and rollback, concurrent group creation, queue deduplication, running reference changes, concurrent manual edits, no-face defaults, access control, same-source publisher/date matching, same-member all-person matching, stable cursors, source text backfill, original bytes, explicit batch scope and split memory.
- Person workflow coverage: atomic create-from-face with groups, accounts, optional reference and rollback, multi-select confirmed references with ownership checks and deduplication, revision conflicts, manual faces without embeddings, deletion preserving images and groups, candidate/undo cleanup, and deletion during a running rematch.
- Real-API browser checks for the person actions: cancel without creating, retry after a failed save, create and confirm with a group, account and reference, multi-select confirmed references and cancel without saving, create from a manual face, cancel/confirm deletion, retained photos, and mobile/dark layouts.
- Publisher coverage: nickname import/backfill and schema migration, Instagram primary-author/coauthor metadata, person filters across platforms with case-insensitive account matching and same-source dates, display-name priority, URL restoration, single-source link suppression, and uppercase X labels.
- Reference avatar coverage: selected-face crop dimensions and pixels, uploaded multi-face selection, legacy box recovery/cache, avatar replacement after reference deletion, private crop access, filter rows without avatars, and desktop/mobile placeholders for missing references.
- Recycle-bin coverage: whole duplicate-group expansion beyond 500 members, scope-token conflicts, atomic processing conflicts, thumbnail/review preservation, reference suspension, migration, pagination, cleanup retry, no resurrection by ordinary import, pre-request download skipping, hash-verified selective restore, cancellation and browser error recovery.
- Cascader coverage: grouped and ungrouped people, overlapping memberships, deduplicated selections and synchronized deselection, search, URL restoration, any/all matching, mobile draft/apply and popup viewport bounds.
- Manual face box coverage: mouse and touch drawing, reverse drags, scaling to original pixels, clamping at image edges, ignoring clicks, cancel/Escape, pointer cancellation, clearing drafts on image changes and retaining drafts after failed saves. Coordinates have no manual input entry.
- Review queue coverage: default union includes unknown/automatic unconfirmed faces, no detections, failed/pending detection and incomplete sources; excludes hidden images and completed manual decisions; confirmed items leave the queue, with other categories still available.
- Review thumbnail network check: Chromium with a mocked 200-group queue at 1440×900 and 390×900 requested 22/15 thumbnails initially with native lazy loading, versus 11/4 with a strip-rooted IntersectionObserver and 124px horizontal headroom. Tests cover scrolling to the final item, returning, and refreshing without duplicate thumbnail requests. These are request counts, not production latency measurements. Related review workflows (17 browser tests), all 29 frontend unit tests, and the production build passed.
- Fast-scroll cancellation: four Chromium cases simulate a direct jump or seven scroll offsets on consecutive animation frames, including reversals, with 250ms delayed thumbnail responses. Offscreen pending fetches now abort; completed blobs remain reusable until their queue entry is removed or the component is disposed. At 1440/390px, rapid scrubbing started 83/35 requests and cancelled 72/31; observed peak in-flight requests fell from 80/31 before cancellation to 22/7. Counts can vary with frame scheduling. Tests verify end-of-queue thumbnails and the selected original load, cancelled images retry on return, completed images are not downloaded twice, and the queue is not refetched. Unit tests cover late bodies after cancellation, metadata refreshes, representative changes, retries and cleanup. Scroll offsets simulate dragging; mocked response delay does not simulate bandwidth limits or HTTP connection contention.
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


## Publisher monitoring and local datetime selection

Monitor tests exercise case-insensitive deduplication, concurrent enqueueing, scheduling,
empty success, overlap, failure progress retention, independent backfill ranges, partial
batches, paused manual work, all resume modes, cancellation races, restart recovery,
retry conflicts, deleted-monitor isolation, interval validation, candidate lookup, and
source timestamp roundtrips. Existing downloader tests cover pinned posts, media-level
deduplication and recycle-bin skips.

Browser tests cover monitor selection and batch conflicts, deletion confirmation,
resume, desktop/mobile light/dark layouts, keyboard datetime entry, local offsets
(including New York DST and Kathmandu), date-only URL warnings, filter refresh/history,
and account import errors preserving entered timestamps. UI screenshots use mocked
API fixtures; they do not verify live platform cookies or remote account availability.
