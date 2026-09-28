"""Versioned diarization profile.

``amix.diarize.mfcc_kmeans.v1`` is the migrated CFS proof: classical MFCC
features and k-means with exactly three clusters. It does not identify
participants and it is not a generic N-speaker diarizer. A later profile can
name a different cluster count without changing ParticipantId.
"""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "amix.diarize.mfcc_kmeans.v1"
IMPLEMENTATION_VERSION = "1"


class InvalidProfile(ValueError):
    def __init__(self) -> None:
        super().__init__(PROFILE_ID)
        self.code = "invalid_diarization_profile"


@dataclass(frozen=True)
class DiarizationProfile:
    profile_id: str
    cluster_count: int
    implementation_version: str


V1 = DiarizationProfile(
    profile_id=PROFILE_ID,
    cluster_count=3,
    implementation_version=IMPLEMENTATION_VERSION,
)


def profile_from_spec(value: object) -> DiarizationProfile:
    if value is None or value == PROFILE_ID:
        return V1
    raise InvalidProfile()
