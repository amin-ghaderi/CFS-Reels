from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

SR = 48000

_PRESET_SFX = {
    "fire_behind_subject": "ignition",
    "glass_crack": "crack",
    "smoke_hit": "soft_boom",
    "electric_spark": "snap",
    "light_burst": "flare",
    "impact_shake": "low_hit",
}


def _env(n: int, attack: int, release: int) -> np.ndarray:
    env = np.ones(n, dtype=np.float64)
    a = max(1, attack)
    r = max(1, release)
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def _stereo(mono: np.ndarray) -> np.ndarray:
    mono = np.asarray(mono, dtype=np.float64)
    peak = float(np.max(np.abs(mono))) + 1e-9
    mono = np.clip(mono / peak * 0.89, -0.89, 0.89)
    return np.stack([mono, mono], axis=1)


def ignition(duration: float, rng: np.random.Generator) -> np.ndarray:
    """Quiet in-scene flare: short crackle, no trailer whoosh."""
    n = int(round(min(0.55, max(0.28, duration * 0.45)) * SR))
    t = np.arange(n) / SR
    noise = rng.normal(0.0, 1.0, n)
    crackle = np.convolve(noise, np.array([1.0, -1.15, 0.35]), mode="same")
    crackle *= np.exp(-t * 9.0)
    pops = np.zeros(n)
    for at in (0.018, 0.041, 0.073, 0.12):
        i0 = int(at * SR)
        k = int(0.008 * SR)
        if 0 <= i0 < n - k:
            pops[i0 : i0 + k] += rng.normal(0, 1, k) * np.linspace(1.0, 0.0, k)
    low = np.sin(2 * math.pi * 52 * t) * np.exp(-t * 7.5) * 0.28
    air = np.convolve(noise, np.ones(48) / 48.0, mode="same") * np.exp(-t * 6.0) * 0.12
    burst = crackle * 0.16 + pops * 0.22 + low + air
    burst *= _env(n, int(0.012 * SR), int(0.18 * SR))
    return _stereo(burst)


def crack(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    clicks = np.zeros(n)
    for at in (0.02, 0.045, 0.07, 0.11):
        i0 = int(at * SR)
        k = int(0.012 * SR)
        if i0 + k < n:
            clicks[i0 : i0 + k] += rng.normal(0, 1, k) * np.linspace(1.0, 0.0, k)
    body = np.sin(2 * math.pi * 180 * t) * np.exp(-t * 28)
    return _stereo(clicks * 0.9 + body * 0.35)


def soft_boom(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    noise = rng.normal(0.0, 1.0, n)
    low = np.sin(2 * math.pi * 42 * t) * np.exp(-t * 4.5)
    air = np.convolve(noise, np.ones(64) / 64.0, mode="same") * np.exp(-t * 5.0)
    return _stereo(low * 0.85 + air * 0.25)


def snap(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    buzz = np.sin(2 * math.pi * 1840 * t) * np.exp(-t * 55)
    noise = rng.normal(0.0, 1.0, n) * np.exp(-t * 40)
    return _stereo(buzz * 0.55 + noise * 0.7)


def flare(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    tone = np.sin(2 * math.pi * 520 * t) * np.exp(-t * 8.0)
    noise = rng.normal(0.0, 1.0, n) * np.exp(-t * 10.0)
    return _stereo(tone * 0.4 + noise * 0.35)


def low_hit(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(round(duration * SR))
    t = np.arange(n) / SR
    body = np.sin(2 * math.pi * 62 * t) * np.exp(-t * 9.0)
    click = rng.normal(0.0, 1.0, n) * np.exp(-t * 60)
    return _stereo(body * 0.9 + click * 0.25)


_BUILDERS = {
    "ignition": ignition,
    "crack": crack,
    "soft_boom": soft_boom,
    "snap": snap,
    "flare": flare,
    "low_hit": low_hit,
}


def sfx_for_preset(preset: str, duration: float, seed: int = 23) -> np.ndarray:
    kind = _PRESET_SFX.get(preset, "low_hit")
    n = max(0.35, min(float(duration), 1.1))
    rng = np.random.default_rng(seed)
    return _BUILDERS[kind](n, rng)


def mix_dialogue_with_sfx(dialogue: np.ndarray, sfx: np.ndarray, gain: float = 0.42) -> np.ndarray:
    if dialogue.ndim == 1:
        dialogue = np.stack([dialogue, dialogue], axis=1)
    out = np.array(dialogue, dtype=np.float64)
    n = min(out.shape[0], sfx.shape[0])
    out[:n] += sfx[:n] * float(gain)
    peak = float(np.max(np.abs(out))) + 1e-9
    if peak > 0.95:
        out *= 0.95 / peak
    return out


def write_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stereo = np.clip(np.asarray(audio, dtype=np.float64), -1.0, 1.0)
    if stereo.ndim == 1:
        stereo = np.stack([stereo, stereo], axis=1)
    pcm = (stereo * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        nch = handle.getnchannels()
        sr = handle.getframerate()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        audio = data.astype(np.float64) / 32768.0
        if nch > 1:
            audio = audio.reshape(-1, nch)[:, :2]
        else:
            audio = np.stack([audio, audio], axis=1)
        return audio, sr
