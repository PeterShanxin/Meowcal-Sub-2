"""Evidence of video motion from the image already captured for subtitle OCR."""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageChops, ImageStat

from meocosub2.audio_observation import AudioObservation
from meocosub2.timeline import PlaybackState

# Work on a small central area above most subtitles and player controls. A
# subtitle-only crop or a black letterbox gives no reliable motion evidence.
SAMPLE_SIZE = (96, 48)
MIN_REGION_SIZE = (320, 180)
MAX_SAMPLE_GAP_S = 5.0
MIN_TEXTURE_STDDEV = 8.0
MIN_MIDTONE_FRACTION = 0.4
MIN_PATCH_DIFFERENCE = 6.0
MAX_FRAME_DIFFERENCE = 45.0
MOTION_WINDOW_S = 1.0
STILL_CONFIRM_S = 0.5
AUDIO_ACTIVE_PEAK = 0.001


class PlaybackObserver:
    """Report motion only when changes span the selected video's image area.

    Stillness remains uncertain: a static shot, a black frame, and a pause can
    look identical. At most eight small grayscale thumbnails are retained in
    memory. The selected OCR rectangle may lack useful video pixels entirely.
    """

    def __init__(self) -> None:
        self._previous: Image.Image | None = None
        self._region: tuple[int, ...] | None = None
        self._sampled_at: float | None = None
        self._moving_pairs = 0
        self._history: deque[tuple[float, Image.Image]] = deque(maxlen=8)
        self._still_since: float | None = None
        self._source_id: int | None = None
        self._audio_was_running = False

    def observe(
        self,
        image: Image.Image,
        region: tuple[int, ...],
        now: float,
        audio: AudioObservation | None = None,
        source_id: int | None = None,
    ) -> PlaybackState:
        if self._previous is not None and (region != self._region or source_id != self._source_id):
            self.reset()
            return PlaybackState.INVALIDATED
        self._source_id = source_id
        if audio is not None and audio.process_id != source_id:
            audio = None
        if not isinstance(image, Image.Image) or len(region) != 4:
            self.reset()
            return PlaybackState.UNCERTAIN
        if (
            image.size != (region[2], region[3])
            or image.width < MIN_REGION_SIZE[0]
            or image.height < MIN_REGION_SIZE[1]
        ):
            self.reset()
            return PlaybackState.UNCERTAIN

        # Exclude rectangle edges, the subtitle rows, controls, and cursor at
        # the bottom. This intentionally declines narrow letterbox-only crops.
        sample = image.crop(
            (
                image.width // 10,
                image.height // 10,
                image.width * 9 // 10,
                image.height * 45 // 100,
            )
        ).convert("L")
        sample = sample.resize(SAMPLE_SIZE, Image.Resampling.BOX)
        prior = self._previous
        adjacent = (
            prior is not None
            and self._region == region
            and self._sampled_at is not None
            and 0 < now - self._sampled_at <= MAX_SAMPLE_GAP_S
        )
        self._previous = sample
        self._region = region
        self._sampled_at = now
        while self._history and now - self._history[0][0] > MOTION_WINDOW_S:
            self._history.popleft()
        baseline = self._history[0][1] if self._history else prior
        self._history.append((now, sample))
        motion = self._motion(sample, prior, baseline, adjacent, now)
        # Some players keep a running stream filled with zeros while paused.
        # A running stream alone is therefore not video progression telemetry.
        if (
            audio is not None
            and audio.running
            and audio.peak is not None
            and audio.peak > AUDIO_ACTIVE_PEAK
        ):
            self._audio_was_running = True
            return PlaybackState.ADVANCING
        if motion is PlaybackState.ADVANCING:
            return motion  # Silent/muted moving video overrides absent audio activity.
        if (
            audio is not None
            and not audio.running
            and self._audio_was_running
            and self._still_since is not None
            and now - self._still_since >= STILL_CONFIRM_S
        ):
            return PlaybackState.STOPPED
        return PlaybackState.UNCERTAIN

    def _motion(self, sample, prior, baseline, adjacent: bool, now: float) -> PlaybackState:
        midtones = sum(sample.histogram()[32:224])
        if (
            not adjacent
            or ImageStat.Stat(sample).stddev[0] < MIN_TEXTURE_STDDEV
            or midtones < SAMPLE_SIZE[0] * SAMPLE_SIZE[1] * MIN_MIDTONE_FRACTION
        ):
            self._moving_pairs = 0
            self._still_since = None
            return PlaybackState.UNCERTAIN

        adjacent_difference = ImageStat.Stat(ImageChops.difference(prior, sample)).mean[0]
        if adjacent_difference < 0.05:
            self._moving_pairs = 0
            if self._still_since is None:
                self._still_since = now
            return PlaybackState.UNCERTAIN
        self._still_since = None
        difference = ImageChops.difference(baseline, sample)
        if ImageStat.Stat(difference).mean[0] > MAX_FRAME_DIFFERENCE:
            self._moving_pairs = 0
            return PlaybackState.UNCERTAIN
        changed: list[tuple[int, int]] = []
        patch_width, patch_height = SAMPLE_SIZE[0] // 4, SAMPLE_SIZE[1] // 2
        for row in range(2):
            for column in range(4):
                patch = difference.crop(
                    (
                        column * patch_width,
                        row * patch_height,
                        (column + 1) * patch_width,
                        (row + 1) * patch_height,
                    )
                )
                if ImageStat.Stat(patch).mean[0] >= MIN_PATCH_DIFFERENCE:
                    changed.append((row, column))
        if len(changed) < 3 or len({row for row, _ in changed}) < 2:
            self._moving_pairs = 0
            return PlaybackState.UNCERTAIN
        if len({column for _, column in changed}) < 3:
            self._moving_pairs = 0
            return PlaybackState.UNCERTAIN
        self._moving_pairs += 1
        return PlaybackState.ADVANCING if self._moving_pairs >= 2 else PlaybackState.UNCERTAIN

    def reset(self) -> None:
        """Discard a sample after capture loss or a selected-region change."""
        self._previous = None
        self._region = None
        self._sampled_at = None
        self._moving_pairs = 0
        self._history.clear()
        self._still_since = None
        self._source_id = None
        self._audio_was_running = False
