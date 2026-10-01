from PIL import Image, ImageChops, ImageDraw

from meocosub2.playback_observation import PlaybackObserver
from meocosub2.timeline import PlaybackState

REGION = (0, 0, 640, 240)


def video_frame() -> Image.Image:
    pixels = bytes(64 + ((x // 7 + y // 7) % 2) * 48 for y in range(240) for x in range(640))
    return Image.frombytes("L", (640, 240), pixels)


def test_distributed_motion_needs_consecutive_frames() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    assert observer.observe(frame, REGION, 0) is PlaybackState.UNCERTAIN
    assert observer.observe(ImageChops.offset(frame, 5, 0), REGION, 0.25) is PlaybackState.UNCERTAIN
    assert observer.observe(ImageChops.offset(frame, 10, 0), REGION, 0.5) is PlaybackState.ADVANCING


def test_stillness_black_frames_and_local_cursor_changes_do_not_claim_motion() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    cursor = frame.copy()
    ImageDraw.Draw(cursor).ellipse((120, 55, 145, 80), fill=255)
    observer.observe(frame, REGION, 0)
    assert observer.observe(frame, REGION, 0.125) is PlaybackState.UNCERTAIN
    assert observer.observe(cursor, REGION, 0.25) is PlaybackState.UNCERTAIN
    assert observer.observe(frame, REGION, 0.5) is PlaybackState.UNCERTAIN
    black = Image.new("L", frame.size)
    assert observer.observe(black, REGION, 0.75) is PlaybackState.UNCERTAIN
    assert observer.observe(black, REGION, 1) is PlaybackState.UNCERTAIN


def test_subtitle_rows_and_controls_below_sample_do_not_claim_motion() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    with_controls = frame.copy()
    ImageDraw.Draw(with_controls).rectangle((0, 170, 639, 239), fill=255)
    observer.observe(frame, REGION, 0)
    assert observer.observe(with_controls, REGION, 0.25) is PlaybackState.UNCERTAIN
    assert observer.observe(frame, REGION, 0.5) is PlaybackState.UNCERTAIN


def test_a_scene_cut_does_not_provide_continuous_motion_evidence() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    cut = ImageChops.invert(frame)
    observer.observe(frame, REGION, 0)
    assert observer.observe(cut, REGION, 0.25) is PlaybackState.UNCERTAIN


def test_capture_region_change_or_long_gap_discards_old_sample() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    moving = ImageChops.offset(frame, 5, 0)
    observer.observe(frame, REGION, 0)
    assert observer.observe(moving, (10, 0, 640, 240), 0.25) is PlaybackState.UNCERTAIN
    assert observer.observe(frame, (10, 0, 640, 240), 10) is PlaybackState.UNCERTAIN
    observer.reset()
    assert observer.observe(moving, (10, 0, 640, 240), 10.25) is PlaybackState.UNCERTAIN


def test_frame_from_a_different_region_size_is_discarded() -> None:
    observer = PlaybackObserver()
    frame = video_frame()
    assert observer.observe(frame, (0, 0, 640), 0) is PlaybackState.UNCERTAIN
    assert observer.observe(frame, (0, 0, 800, 240), 0) is PlaybackState.UNCERTAIN
    assert observer.observe(ImageChops.offset(frame, 5, 0), REGION, 0.25) is PlaybackState.UNCERTAIN


def test_subtitle_only_crop_stays_uncertain() -> None:
    observer = PlaybackObserver()
    frame = video_frame().crop((0, 160, 640, 240))
    assert observer.observe(frame, (0, 160, 640, 80), 0) is PlaybackState.UNCERTAIN
    assert (
        observer.observe(ImageChops.offset(frame, 5, 0), (0, 160, 640, 80), 0.25)
        is PlaybackState.UNCERTAIN
    )


def test_letterbox_with_changing_subtitles_stays_uncertain() -> None:
    observer = PlaybackObserver()
    frame = Image.new("L", (640, 240))
    for second, text in enumerate(("One line", "Two lines", "A third")):
        with_subtitle = frame.copy()
        draw = ImageDraw.Draw(with_subtitle)
        draw.text((190, 45), text * 4, fill=255)
        draw.text((190, 75), text * 4, fill=255)
        assert observer.observe(with_subtitle, REGION, second * 0.25) is PlaybackState.UNCERTAIN
