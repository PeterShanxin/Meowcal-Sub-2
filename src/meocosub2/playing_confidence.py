"""Fuse observable progression and apply a sustained player-freeze policy."""

from __future__ import annotations

import math

from meocosub2.audio_observation import AudioObservation
from meocosub2.subtitle_gate import normalize
from meocosub2.timeline import MAX_PLAYBACK_SAMPLE_GAP_S, PlaybackState

# Reproduced by scripts/fit_playing_confidence.py from 288 authored physical
# FFplay/Edge samples and balanced indistinguishable static observations.
# These are an evidence index, not a probability calibrated on arbitrary media.
# The still/silent pause and static-playing pair deliberately share observations.
COEFFICIENTS = (0.311437, 1.422677, 0.029923, 2.251407, -0.356064, 0.0, -0.103645)
ENTER_SCORE = 0.704544
LEAVE_SCORE = 0.628153
AMBIGUOUS_SCORE = 0.551762
SUPPORTING_SCORE = 0.559150
EVIDENCE_WINDOW_S = 1.0
FREEZE_CONFIRM_S = 2.0


class PlayingConfidence:
    """Keep image motion, confirmed text changes and audio as separate features.

    Image motion has already required distributed consecutive changes. Text
    changes require consecutive matching reads. Recent strong evidence decays
    over the measured image window; separate entry/exit scores resist flicker.
    A separate two-second freeze heuristic holds an existing clock. It is not
    a calibrated pause probability: silent static content can also trigger it.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._at: float | None = None
        self._features = [False] * 6
        self._previous_text: str | None = None
        self._stable_text: str | None = None
        self._text_at = -float("inf")
        self._changed_at = -float("inf")
        self._supported_at = -float("inf")
        self._supported_score = 0.0
        self._advancing = False
        self._audio: AudioObservation | None = None
        self._visual_at = -float("inf")
        self._quiet_since: float | None = None
        self._still_since: float | None = None
        self._motion_since: float | None = None
        self._stopped_at: float | None = None
        self.state_since: float | None = None
        self.confidence = 0.5

    @property
    def stopped(self) -> bool:
        return self._stopped_at is not None

    def observe(
        self,
        motion: bool,
        still: bool,
        audio: AudioObservation | None,
        at: float,
        *,
        still_since: float | None = None,
        motion_since: float | None = None,
    ) -> PlaybackState:
        if self._at is not None and (at <= self._at or at - self._at > MAX_PLAYBACK_SAMPLE_GAP_S):
            self.reset()
        self._at = at
        self._audio = audio
        self._still_since = still_since
        self._motion_since = motion_since
        audible = (
            audio is not None and audio.running and audio.peak is not None and audio.peak > 0.001
        )
        silent = audio is not None and audio.peak is not None and audio.peak <= 0.001
        fresh_text = at - self._text_at <= EVIDENCE_WINDOW_S
        changed = at - self._changed_at <= EVIDENCE_WINDOW_S
        self._features = [
            motion,
            changed,
            audible and (motion or changed or (audio is not None and audio.attributed)),
            silent,
            fresh_text and self._stable_text is not None,
            still,
        ]
        return self._judge(at)

    def observe_text(self, text: str, at: float) -> PlaybackState:
        if self._at != at:
            return PlaybackState.UNCERTAIN
        current = normalize(text)
        stable = current == self._previous_text and at - self._text_at <= EVIDENCE_WINDOW_S
        if stable:
            if current and self._stable_text is not None and current != self._stable_text:
                self._changed_at = at
            self._stable_text = current
        self._previous_text, self._text_at = current, at
        self._features[1] = at - self._changed_at <= EVIDENCE_WINDOW_S
        self._features[4] = stable
        if self._audio is not None and not self._audio.attributed:
            self._features[2] = (
                self._audio.peak is not None
                and self._audio.running
                and self._audio.peak > 0.001
                and (self._features[0] or self._features[1])
            )
        return self._judge(at)

    def _judge(self, at: float) -> PlaybackState:
        logit = COEFFICIENTS[0] + sum(
            weight * value for weight, value in zip(COEFFICIENTS[1:], self._features, strict=True)
        )
        score = 1 / (1 + math.exp(-logit))
        weak_sound = (
            self._audio is not None
            and not self._audio.attributed
            and self._audio.running
            and self._audio.peak is not None
            and self._audio.peak > 0.001
        )
        if weak_sound and not self._features[0]:
            # A changing overlay and unrelated sound can coincide on a paused
            # web video. They add support, but cannot certify image progression.
            score = min(max(score, SUPPORTING_SCORE), (SUPPORTING_SCORE + ENTER_SCORE) / 2)
        if self._features[0] or self._features[1]:
            self._visual_at = at
        if score >= ENTER_SCORE:
            self._supported_at, self._supported_score = at, score
        retained = max(0.0, 1 - (at - self._supported_at) / EVIDENCE_WINDOW_S)
        self.confidence = score + max(0.0, self._supported_score - score) * retained
        trusted_sound = self._audio is not None and self._audio.attributed and self._features[2]
        ambiguous = (
            self._features[5]
            and self._features[4]
            and not self._features[0]
            and not self._features[1]
            and not trusted_sound
        )
        if ambiguous:
            # These observations are shared by a real pause and a naturally
            # static silent scene. The model's class proportions cannot resolve
            # that ambiguity, including with unrelated sound or a recent cue.
            self.confidence = min(self.confidence, AMBIGUOUS_SCORE)
        expired_context = weak_sound and at - self._visual_at > EVIDENCE_WINDOW_S
        if ambiguous or expired_context or self.confidence < LEAVE_SCORE:
            self._advancing = False
        elif self.confidence >= ENTER_SCORE:
            self._advancing = True
        return self._freeze_state(at, trusted_sound)

    def _freeze_state(self, at: float, trusted_sound: bool) -> PlaybackState:
        # OCR can correct a seek while stopped, but only independent image or
        # attributed sound resumes the player. A new source cue can be a seek
        # on a paused frame, so it must not release an already confirmed stop.
        if self._features[0] or trusted_sound:
            self._stopped_at = None
            self._quiet_since = None
            self.state_since = self._motion_since if self._features[0] else at
            return PlaybackState.ADVANCING if self._advancing else PlaybackState.UNCERTAIN
        if self._stopped_at is not None:
            return PlaybackState.STOPPED
        if self._quiet_since is None:
            self._quiet_since = at
        if self._still_since is not None or self._features[5]:
            onset = max(
                self._quiet_since,
                self._still_since if self._still_since is not None else self._quiet_since,
            )
            self.state_since = onset
            if self._features[5] and at >= onset + FREEZE_CONFIRM_S:
                self._stopped_at = at
                return PlaybackState.STOPPED
        else:
            self.state_since = None
        return PlaybackState.ADVANCING if self._advancing else PlaybackState.UNCERTAIN
