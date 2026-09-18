from __future__ import annotations

import pytest

from scripts.lock_backend_requirements import (
    LOCK,
    Pin,
    lock_problems,
    merge_platforms,
    parse_lock,
    render_lock,
)

X64 = "a" * 64
ARM64 = "b" * 64
OTHER = "c" * 64


def pins(*items: Pin) -> dict[str, Pin]:
    return {item.name.lower().replace("_", "-"): item for item in items}


def test_committed_lock_is_in_generated_form() -> None:
    text = LOCK.read_text(encoding="utf-8")

    assert render_lock(parse_lock(text)) == text


def test_parse_accepts_continuation_lines_and_comments() -> None:
    text = f"# header\nPillow==12.3.0 \\\n    --hash=sha256:{X64} \\\n    --hash=sha256:{ARM64}\n"

    assert parse_lock(text) == {"pillow": Pin("Pillow", "12.3.0", frozenset({X64, ARM64}))}


@pytest.mark.parametrize(
    "text",
    [
        "pillow>=12.3.0\n",
        "pillow==12.3.0\n",
        f"pillow==12.3.0 --hash=sha256:{X64}\nPillow==12.3.0 --hash=sha256:{X64}\n",
    ],
)
def test_parse_rejects_unpinned_unhashed_and_duplicate_lines(text: str) -> None:
    with pytest.raises(ValueError):
        parse_lock(text)


def test_platforms_merge_wheel_hashes_for_one_version() -> None:
    merged = merge_platforms(
        {
            "win_amd64": pins(Pin("pillow", "12.3.0", frozenset({X64}))),
            "win_arm64": pins(Pin("pillow", "12.3.0", frozenset({ARM64}))),
        }
    )

    assert merged == pins(Pin("pillow", "12.3.0", frozenset({X64, ARM64})))


def test_platforms_must_agree_on_the_version() -> None:
    with pytest.raises(ValueError, match="pillow"):
        merge_platforms(
            {
                "win_amd64": pins(Pin("pillow", "12.3.0", frozenset({X64}))),
                "win_arm64": pins(Pin("pillow", "12.4.0", frozenset({ARM64}))),
            }
        )


def test_matching_lock_passes_even_with_extra_artifact_hashes() -> None:
    resolved = pins(Pin("pillow", "12.3.0", frozenset({X64, ARM64})))
    lock = pins(Pin("pillow", "12.3.0", frozenset({X64, ARM64, OTHER})))

    assert lock_problems(lock, resolved) == []


@pytest.mark.parametrize(
    ("lock", "problem"),
    [
        ({}, "missing pillow==12.3.0"),
        (pins(Pin("pillow", "12.2.0", frozenset({X64, ARM64}))), "pinned at 12.2.0"),
        (pins(Pin("pillow", "12.3.0", frozenset({X64}))), "lacks a selected wheel hash"),
    ],
)
def test_lock_that_would_not_install_what_resolves_fails(
    lock: dict[str, Pin], problem: str
) -> None:
    resolved = pins(Pin("pillow", "12.3.0", frozenset({X64, ARM64})))

    assert [problem in message for message in lock_problems(lock, resolved)] == [True]


def test_lock_entry_nothing_requires_fails() -> None:
    lock = pins(Pin("colorama", "0.4.6", frozenset({X64})))

    assert lock_problems(lock, {}) == ["unused colorama==0.4.6"]
