from __future__ import annotations

from dataclasses import dataclass

PRESET_NAMES = (
    "fire_behind_subject",
    "glass_crack",
    "smoke_hit",
    "electric_spark",
    "light_burst",
    "impact_shake",
)

MIN_DURATION_S = 0.8
MAX_DURATION_S = 2.5
DEFAULT_DURATION_S = 1.2
SPEAKER_KEYS = ("speaker_a", "speaker_b", "speaker_c")


@dataclass(frozen=True)
class VisualHookConfig:
    enabled: bool
    preset: str
    target_speaker: str
    start_time: float | None
    duration: float
    intensity: float
    sfx_enabled: bool

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "preset": self.preset,
            "target_speaker": self.target_speaker,
            "start_time": self.start_time,
            "duration": self.duration,
            "intensity": self.intensity,
            "sfx_enabled": self.sfx_enabled,
        }


def clamp_duration(value: float) -> float:
    return min(MAX_DURATION_S, max(MIN_DURATION_S, float(value)))


def parse_visual_hook(raw) -> VisualHookConfig | None:
    """Parse an optional visual_hook block.

    Missing or disabled config returns None so callers can skip the module.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("visual_hook must be an object")
    if not raw:
        return None
    enabled = bool(raw.get("enabled", False))
    preset = str(raw.get("preset") or "").strip()
    speaker = str(raw.get("target_speaker") or "").strip()
    if speaker and speaker not in SPEAKER_KEYS:
        raise ValueError(f"visual_hook target_speaker must be one of {SPEAKER_KEYS}")
    if preset and preset not in PRESET_NAMES:
        raise ValueError(f"Unknown visual_hook preset: {preset!r}")
    start = raw.get("start_time")
    start_time = None if start is None or start == "" else float(start)
    duration = clamp_duration(raw.get("duration", DEFAULT_DURATION_S))
    intensity = float(raw.get("intensity", 0.7))
    intensity = min(1.0, max(0.05, intensity))
    sfx_enabled = bool(raw.get("sfx_enabled", True))
    if not enabled:
        return VisualHookConfig(
            enabled=False,
            preset=preset or PRESET_NAMES[0],
            target_speaker=speaker or "speaker_c",
            start_time=start_time,
            duration=duration,
            intensity=intensity,
            sfx_enabled=sfx_enabled,
        )
    if not preset:
        raise ValueError("visual_hook.preset is required when enabled")
    if not speaker:
        raise ValueError("visual_hook.target_speaker is required when enabled")
    return VisualHookConfig(
        enabled=True,
        preset=preset,
        target_speaker=speaker,
        start_time=start_time,
        duration=duration,
        intensity=intensity,
        sfx_enabled=sfx_enabled,
    )


def visual_hook_enabled(plan: dict | None) -> bool:
    """Integration gate: False unless a plan explicitly enables a visual hook."""
    if not isinstance(plan, dict):
        return False
    cfg = parse_visual_hook(plan.get("visual_hook"))
    return cfg is not None and cfg.enabled
