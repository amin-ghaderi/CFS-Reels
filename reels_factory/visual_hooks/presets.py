from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .vfx import (
    electric_spark,
    fire_behind,
    glass_crack,
    impact_shake,
    light_burst,
    smoke_hit,
)

PresetFn = Callable[[np.ndarray, np.ndarray, float, float, float], np.ndarray]

PRESETS: dict[str, dict] = {
    "fire_behind_subject": {
        "fn": fire_behind,
        "needs_matte": True,
        "layer": "behind",
        "sfx": "ignition",
    },
    "glass_crack": {
        "fn": glass_crack,
        "needs_matte": True,
        "layer": "localized",
        "sfx": "crack",
    },
    "smoke_hit": {
        "fn": smoke_hit,
        "needs_matte": True,
        "layer": "behind",
        "sfx": "soft_boom",
    },
    "electric_spark": {
        "fn": electric_spark,
        "needs_matte": True,
        "layer": "localized",
        "sfx": "snap",
    },
    "light_burst": {
        "fn": light_burst,
        "needs_matte": True,
        "layer": "behind",
        "sfx": "flare",
    },
    "impact_shake": {
        "fn": impact_shake,
        "needs_matte": False,
        "layer": "camera",
        "sfx": "low_hit",
    },
}


def apply_preset(
    name: str,
    frame: np.ndarray,
    matte: np.ndarray,
    t: float,
    duration: float,
    intensity: float,
) -> np.ndarray:
    spec = PRESETS.get(name)
    if spec is None:
        raise ValueError(f"Unknown visual hook preset: {name!r}")
    fn: PresetFn = spec["fn"]
    return fn(frame, matte, t, duration, intensity)
