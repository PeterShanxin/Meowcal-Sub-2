# Meowcal Core

Meowcal Core supplies Windows OCR, PP-OCRv6 and managed HY-MT inference through a
versioned process API. Canonical source and Windows ARM64/x64 runtime releases
live in [Meowcal-Sub](https://github.com/PeterShanxin/Meowcal-Sub/tree/main/core).
Sub 2 consumes a runtime artifact; it does not import Rust source or launch the
Sub 1 application. Change Core in that repository, not here. The
[Core README](https://github.com/PeterShanxin/Meowcal-Sub/blob/main/core/README.md#api-1)
owns the API 1 protocol; this document covers how Sub 2 uses it.

## Versions and capabilities

These are independent:

| Item | Where it is set | What it means |
| --- | --- | --- |
| App version | The app manifests (see the [developer guide](developer-guide.md#build-a-windows-distribution)) | The Sub 2 release |
| Core release version | `coreVersion` and `tag` in [`config/meowcal-core.lock.json`](../config/meowcal-core.lock.json) | The Core package every build of this checkout bundles |
| API major | `apiVersion` in the lock | The protocol generation; the handshake rejects another major |
| Capabilities | The Core handshake at run time | The optional features this Core process offers |

The lock decides which Core a build contains. The handshake decides what the
running Core can do. A Core upgrade does not enable a new capability by itself:
Sub 2 uses a capability only where its own code requests it, after the
handshake reports it. For example, PP-OCRv6 needs the `ocrPpOcrV6`
capability, which Core 0.2.2 offers; the published App v0.2.2 bundles Core
0.1.4 and has no PP-OCRv6 support.

## Ownership

Core owns the HY-MT manifest, artifact verification, installation/recovery, GPU
policy, managed inference process, and raw recognition. Sub 2 owns screen capture,
OCR preprocessing and pass selection, subtitle search/matching, BGE embeddings,
gap filling, prompts and output acceptance, the playback timeline, and UI.

OCR has its own Core process, separate from translation. A model request cannot
occupy the recognition transport. The raw OCR boundary returns recognized lines
and geometry. Sharing native recognition does not establish that one product's
preprocessing is better for the other's workload.

## OCR engine selection

`capture.ocr_engine` is `auto`, `windows`, or `ppOcrV6` (**Settings → Capture →
OCR engine**). The OCR language follows the source language. The backend
resolves the engine when a session starts and records the requested and
resolved engine in the `ocr.engine.ready` event. A changed setting applies to
the next start.

| Setting | Session with a source file | Session without a source file |
| --- | --- | --- |
| Automatic | Windows OCR when the exact language pack is installed; otherwise PP-OCRv6 for a supported language; otherwise Windows OCR with a compatible pack | Windows OCR with the exact or a compatible pack; otherwise PP-OCRv6 for a supported language |
| Windows OCR | Windows OCR with the exact or a compatible pack | Same |
| PP-OCRv6 | PP-OCRv6 for a supported language; otherwise Windows OCR | Same |

- PP-OCRv6 languages in Sub 2 are English, Chinese, Japanese, Spanish, French,
  and German. Korean always uses Windows OCR.
- Compatible Windows packs are Simplified and Traditional Chinese for each other,
  and English (United Kingdom) for English (United States). The session records
  a warning that names the substitution.
- Sessions without a source file prefer Windows OCR because PP-OCRv6 reads more
  scene text, and no source track can reject it (see
  [OCR measurements](OCR_BENCHMARK.md)).
- When Core lacks `ocrPpOcrV6`, the session uses Windows OCR with the warning
  "PP-OCRv6 is unavailable. Using Windows OCR." When initialization fails, the
  warning is "PP-OCRv6 could not start. Using Windows OCR." An explicit PP-OCRv6
  setting with an unsupported language gives "PP-OCRv6 does not support this
  language. Using Windows OCR."
- When Windows OCR is the result and no usable pack is installed, start fails with
  a message that names the missing language pack.

The warnings above become the session warning when the session starts. The live
dock shows it during the session, and it remains after the session stops until
a later search, preparation, subtitle save, start, or error replaces it. `ocr.engine.ready` records
the requested and resolved engine.

PP-OCRv6 reads the original image once with two threads. Sub 2 removes lines
shorter than 60% of the tallest detected line before matching.

Windows OCR compares the original image, an equalized image, and a neutral-white
text mask. The mask can recover rows hidden by scene texture only when it retains
at least 80% of the ordered letters from a whole-scene read with at least three
letters. This preserves colored or dim subtitles when white scenery produces
unrelated text. Eligible reads compete on cleaned text quality, not physical row
count. Each pass waits at most one second. A timeout returns the best prior read
and terminates the owned OCR Core process; a new process handles later frames.
Recognition never queues behind model inference.

BGE retains its own model and process implementation and a separate runtime
directory. It must not execute files from a Core installation without a lifetime
lease. No BGE code uses Sub 1's cache as its primary runtime location.

## Compatibility and coexistence

Sub 2 pins an exact Core version, API major, architecture, and artifact digest.
The process handshake verifies version and required capabilities before any
recognition, installation, or inference. Missing or incompatible runtimes are
reported explicitly. There is no automatic selection of a global latest Core.

Core's managed port is a preference, not its bound address. Translation stays
on the Core RPC channel; Sub 2 does not publish that preference as a live HTTP
endpoint. Readiness is cached only for the Core process generation that confirmed it.

Cancelling an active subtitle translation discards the answer while the client
drains its response within the original deadline, keeping the model loaded.
Transport failures terminate the owned Core process; the next translation
re-establishes readiness for the replacement process.

Core data defaults to
`%LOCALAPPDATA%/Meowcal/Core/<client>/<profile>/<version>/<architecture>`, and
Sub 2's client is `sub2`. The profile separates development from production.
Custom storage keeps the same partitions below its base. Each application owns
its processes and shutdown does not stop another application's engine.

An install imports a verified runtime archive or model from another partition of
the same profile and architecture as an NTFS hard link, including Sub 1's and
the unpartitioned layout Core 0.1.0 to 0.1.3 wrote, and copies only where the
volume cannot link. Once its engine is ready, Core removes Sub 2's other
versions except the newest complete one, kept for rollback, and replaces
matching models in the remaining partitions with links to its own.

Running engines retain shared installation leases; install/repair requires an
exclusive lease with a bounded wait. A busy installation reports that conflict
instead of replacing files in use, and reclaim skips partitions another process
holds. Upgrading Sub 1 cannot change Sub 2's pin or remove Sub 2's partition.
Rollback reinstates the prior application and pin; a version whose partition
was removed imports the model again as a link.

OCR uses `ocrRecognizeBgra`: a UTF-8 JSON header ending in a newline, followed
by exactly `payloadBytes` raw BGRA bytes without a trailing delimiter. Control
requests carry zero payload bytes. All JSON headers and responses are limited to
256 KiB; packed OCR frames are limited to 4096 pixels per dimension and 64 MiB.
The header carries dimensions, packed stride, and a 1–30000 ms timeout. Windows
requests carry `language` and omit `engine` and `maxThreads`. PP-OCRv6 requests
require the additive `ocrPpOcrV6` capability, set `engine: "ppOcrV6"` and
`maxThreads: 2`, and omit `language`; the client rejects a request that mixes
the two forms. Before capture, `ocrInitialize` loads the PP-OCRv6 model with its
own cancellable budget, separate from the one-second frame deadline. The
response must name `ppOcrV6` and no resolved language. Process replacement
invalidates that initialization.
The client deadline includes writing the complete header and pixels. Cancellation,
a stalled write, or malformed framing terminates the owned OCR process before
a later request starts a replacement. The handshake requires the binary OCR
capability; incompatible runtimes cannot fall back to Base64.

Async OCR uses its existing event-loop deadline to abort the process and drain
the worker, avoiding a new timer thread for every recognition pass. This requires
the event loop to remain responsive; Core separately enforces its native OCR
deadline. Synchronous calls and translations retain an independent timer because
a cancelled translation may keep draining after its caller has left.

Language discovery is cached across captured frames. Initial discovery runs off
the event loop; explicit language-list refresh replaces the cache, and OCR
shutdown clears it. The launcher reuses prepared Core resources only when the
release lock and executable, metadata, and license hashes match the preparation
receipt. File timestamps do not determine whether Core needs downloading.

## Existing installations

Legacy roots are import candidates, not live dependencies. Core verifies a
candidate archive and model against its embedded manifest, copies them, verifies
the copies, and re-extracts the runtime. It never trusts an adjacent DLL merely
because the old executable has the right size or hash. It does not delete or
hard-link the old files. Missing or invalid artifacts use the normal Settings
install/repair flow.

Earlier Sub 2 installers deleted the runtime archive after installation. Those
installations can reuse the verified 1.13 GB model, but Settings Install must
download the missing runtime archive (about 13 MB on ARM64 or 34 MB on x64).
Readiness never starts a network download. Installations retaining both verified
artifacts can migrate offline.

Application configuration, subtitle files, matching state, and BGE data remain
owned by Sub 2. Importing an engine does not rewrite those files or change their
schemas.

## Verification

The normal verifier includes consumer contract tests. Release acceptance also
requires running both consumers against the actual pinned Core binary, native
OCR with known images, real HY-MT inference, concurrent application use, interrupted
installation, and rollback. Windows ARM64 evidence does not prove x64 behavior;
hosted tests do not replace the real-device gate.
