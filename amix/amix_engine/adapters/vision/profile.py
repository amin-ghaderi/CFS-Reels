"""Overlap profile. Thresholds are the CFS proof. They are not retuned here.

The activity columns are participant ids. The proof was measured on a
three-person frame, and a region still requires two articulating participants.
This profile does not name tiles or fix the participant count at three.
"""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "amix.overlap.lip_audio.v1"
IMPLEMENTATION_VERSION = "1"
MIN_VISIBLE_PARTICIPANTS = 2


class InvalidProfile(ValueError):
    def __init__(self) -> None:
        super().__init__(PROFILE_ID)
        self.code = "invalid_overlap_profile"


@dataclass(frozen=True)
class OverlapProfile:
    profile_id: str
    implementation_version: str
    sample_fps: int
    window_s: float
    step_s: float
    simultaneous_s: float
    min_windows: int
    merge_gap_s: float
    lip_on: float
    weaker_min: float
    min_region_s: float
    analysis_tile_w: int
    analysis_tile_h: int
    min_visible_participants: int


V1 = OverlapProfile(
    profile_id=PROFILE_ID,
    implementation_version=IMPLEMENTATION_VERSION,
    sample_fps=8,
    window_s=1.25,
    step_s=0.25,
    simultaneous_s=0.75,
    min_windows=2,
    merge_gap_s=0.75,
    lip_on=4.2,
    weaker_min=5.5,
    min_region_s=2.5,
    analysis_tile_w=448,
    analysis_tile_h=252,
    min_visible_participants=MIN_VISIBLE_PARTICIPANTS,
)


def profile_from_spec(value: object) -> OverlapProfile:
    if value is None or value == PROFILE_ID:
        return V1
    raise InvalidProfile()


def profile_config(profile: OverlapProfile) -> dict:
    return {
        "profile_id": profile.profile_id,
        "sample_fps": profile.sample_fps,
        "window_s": profile.window_s,
        "step_s": profile.step_s,
        "simultaneous_s": profile.simultaneous_s,
        "min_windows": profile.min_windows,
        "merge_gap_s": profile.merge_gap_s,
        "lip_on": profile.lip_on,
        "weaker_min": profile.weaker_min,
        "min_region_s": profile.min_region_s,
        "analysis_tile_w": profile.analysis_tile_w,
        "analysis_tile_h": profile.analysis_tile_h,
        "min_visible_participants": profile.min_visible_participants,
        "audio_gate": "percentile_25_of_positive_rms",
        "measurement": "layout_crop_resampled_to_analysis_tile",
    }
