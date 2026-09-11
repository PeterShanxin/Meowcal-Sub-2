# Meowcal Core

Meowcal Core supplies native Windows OCR and managed HY-MT inference through a
versioned process API. Canonical source and Windows ARM64/x64 runtime releases
live in [Meowcal-Sub](https://github.com/PeterShanxin/Meowcal-Sub/tree/main/core).
Sub 2 consumes a runtime artifact; it does not import Rust source or launch the
Sub 1 application.

## Ownership

Core owns the HY-MT manifest, artifact verification, installation/recovery, GPU
policy, managed inference process, and raw Windows OCR. Sub 2 owns screen capture,
OCR preprocessing and pass selection, subtitle search/matching, BGE embeddings,
gap filling, prompts and output acceptance, the playback timeline, and UI.

OCR has its own Core process, separate from translation. A model request cannot
occupy the recognition transport. The raw OCR boundary returns recognized lines
and geometry; the existing three-pass selection and white-mask corroboration
remain in the capture pipeline. Sharing native recognition does not establish
that one product's preprocessing is better for the other's workload.

BGE retains its own model and process implementation and a separate runtime
directory. It must not execute files from a Core installation without a lifetime
lease. No BGE code uses Sub 1's cache as its primary runtime location.

## Compatibility and coexistence

Sub 2 pins an exact Core version, API major, architecture, and artifact digest.
The process handshake verifies version and required capabilities before any
recognition, installation, or inference. Missing or incompatible runtimes are
reported explicitly. There is no automatic selection of a global latest Core.

Cancelling an active subtitle translation discards the answer while the client
drains its response within the original deadline, keeping the model loaded.
Transport failures terminate the owned Core process; the next translation
re-establishes readiness for the replacement process.

Core data defaults to
`%LOCALAPPDATA%/Meowcal/Core/<profile>/<version>/<architecture>`. The profile
separates development from production. Custom storage retains version and
architecture partitions. Each application owns its processes and shutdown does
not stop another application's engine.

Running engines retain shared installation leases; install/repair requires an
exclusive lease with a bounded wait. A busy installation reports that conflict
instead of replacing files in use. Upgrading Sub 1 cannot change Sub 2's pin or
remove the old Core version. Rollback reinstates the prior application and pin;
older data directories are retained.

OCR uses `ocrRecognizeBgra`: a UTF-8 JSON header ending in a newline, followed
by exactly `payloadBytes` raw BGRA bytes without a trailing delimiter. Control
requests carry zero payload bytes. All JSON headers and responses are limited to
256 KiB; packed OCR frames are limited to 4096 pixels per dimension and 64 MiB.
The header carries language, dimensions, packed stride, and a 1–30000 ms timeout.
The client deadline includes writing the complete header and pixels. Cancellation,
a stalled write, or malformed framing terminates the owned OCR process before
a later request starts a replacement. The handshake requires the binary OCR
capability; incompatible runtimes cannot fall back to Base64.

Async OCR uses its existing event-loop deadline to abort the process and drain
the worker, avoiding a new timer thread for every recognition pass. This requires
the event loop to remain responsive; Core separately enforces its native OCR
deadline. Synchronous calls and translations retain an independent timer because
a cancelled translation may keep draining after its caller has left.

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
