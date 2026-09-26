# Cinematic trailer mix of CFS03_summary_01. Does not touch Reels or the original summary MP4.
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

from reels_factory.config import load_config
from reels_factory.framing import layout_from_framing_profile, resolve_framing_profile
from reels_factory.render import _accurate_cut_args, _resolve_source_video
from reels_factory.utils import parse_timestamp, read_json, require_binary, run, write_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01.json"
TRAILER_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01_trailer.json"
ORIGINAL_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01.mp4"
OUT_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer.mp4"
ASSETS = ROOT / "data" / "episode_summaries" / "trailer_assets"
STACK = ("speaker_a", "speaker_c", "speaker_b")
SR = 48000
FPS = 30
W, H = 1080, 1920


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lock_editorial(source: dict, trailer: dict) -> None:
    if trailer.get("source_plan") != "data/episode_summaries/CFS03_summary_01.json":
        raise ValueError("Trailer plan must point at CFS03_summary_01.json")
    src_segs = source["segments"]
    if len(src_segs) != 8:
        raise ValueError("Expected 8 summary excerpts")
    for left, right in zip(src_segs, src_segs):
        if left["start"] != right["start"] or left["end"] != right["end"] or left["text"] != right["text"]:
            raise ValueError("Editorial lock failed")
    if list(source.get("stack_order") or []) != list(STACK):
        raise ValueError("Summary stack order must stay A/C/B")


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
        n = handle.getnframes()
        raw = handle.readframes(n)
        width = handle.getsampwidth()
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    else:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    if nch > 1:
        data = data.reshape(-1, nch)
        if nch != 2:
            data = data[:, :2]
    else:
        data = np.stack([data, data], axis=1)
    return data, sr


def resample_stereo(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    n = audio.shape[0]
    t_src = np.linspace(0.0, 1.0, n, endpoint=False)
    n_dst = int(round(n * dst_sr / src_sr))
    t_dst = np.linspace(0.0, 1.0, n_dst, endpoint=False)
    left = np.interp(t_dst, t_src, audio[:, 0])
    right = np.interp(t_dst, t_src, audio[:, 1])
    return np.stack([left, right], axis=1)


def _exp_sweep(n: int, f0: float, f1: float, sr: int) -> np.ndarray:
    t = np.arange(n) / sr
    if n <= 1:
        return np.zeros(n)
    k = math.log(f1 / f0)
    phase = 2 * math.pi * f0 * (np.expm1(k * t) / k)
    return np.sin(phase)


def _fade(n: int, attack: int, release: int) -> np.ndarray:
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    env = np.ones(n, dtype=np.float64)
    attack = max(0, min(int(attack), n))
    release = max(0, min(int(release), n))
    if attack + release > n:
        attack = max(1, n // 5)
        release = max(1, n - attack)
    if attack > 0:
        env[:attack] = np.linspace(0.0, 1.0, attack, endpoint=True)
    if release > 0:
        env[-release:] = np.linspace(1.0, 0.0, release, endpoint=True)
    return env


def generate_sfx(assets: Path) -> dict[str, Path]:
    assets.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(23)

    def stereo_from_mono(mono: np.ndarray, width: float = 0.12) -> np.ndarray:
        late = np.pad(mono, (int(0.0012 * SR), 0))[: mono.shape[0]] * width
        left = mono + late
        right = mono - late
        peak = max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-9)
        gain = 0.9 / peak
        return np.stack([left * gain, right * gain], axis=1)

    n_whoosh = int(0.22 * SR)
    noise = rng.normal(0, 1, n_whoosh)
    whoosh = np.convolve(noise, np.ones(48) / 48, mode="same")
    whoosh *= _fade(n_whoosh, int(0.03 * SR), int(0.12 * SR))
    t = np.arange(n_whoosh) / SR
    whoosh *= (0.35 + 0.65 * t / t[-1])
    whoosh_path = assets / "sfx_whoosh_short.wav"
    write_wav(whoosh_path, stereo_from_mono(whoosh * 0.55))

    rev = np.flip(whoosh) * _fade(n_whoosh, int(0.02 * SR), int(0.08 * SR))
    rev_path = assets / "sfx_whoosh_reverse.wav"
    write_wav(rev_path, stereo_from_mono(rev * 0.5))

    n_imp = int(0.38 * SR)
    kick = _exp_sweep(n_imp, 140, 38, SR) * _fade(n_imp, 8, int(0.32 * SR))
    click = rng.normal(0, 1, n_imp) * _fade(n_imp, 4, int(0.04 * SR)) * 0.12
    impact = kick * 0.9 + click
    impact_path = assets / "sfx_impact_low.wav"
    write_wav(impact_path, stereo_from_mono(impact * 0.7, 0.04))

    n_hit = int(0.12 * SR)
    hit = rng.normal(0, 1, n_hit) * _fade(n_hit, 3, int(0.09 * SR))
    hit = np.convolve(hit, np.ones(20) / 20, mode="same")
    hit_path = assets / "sfx_hit_soft.wav"
    write_wav(hit_path, stereo_from_mono(hit * 0.45))

    n_riser = int(1.15 * SR)
    riser = _exp_sweep(n_riser, 80, 420, SR) * 0.22
    air = rng.normal(0, 1, n_riser)
    air = np.convolve(air, np.ones(30) / 30, mode="same") * np.linspace(0.05, 0.55, n_riser)
    riser = (riser + air) * np.linspace(0.05, 1.0, n_riser)
    riser *= _fade(n_riser, int(0.05 * SR), int(0.12 * SR))
    riser_path = assets / "sfx_riser.wav"
    write_wav(riser_path, stereo_from_mono(riser * 0.55, 0.18))

    n_pulse = int(0.28 * SR)
    pulse = _exp_sweep(n_pulse, 90, 42, SR) * _fade(n_pulse, 6, int(0.22 * SR))
    pulse_path = assets / "sfx_bass_pulse.wav"
    write_wav(pulse_path, stereo_from_mono(pulse * 0.75, 0.03))

    existing = ROOT / "assets" / "sounds" / "whoosh_soft.wav"
    return {
        "whoosh_short": whoosh_path,
        "whoosh_reverse": rev_path,
        "impact_low": impact_path,
        "hit_soft": hit_path,
        "riser": riser_path,
        "bass_pulse": pulse_path,
        "whoosh_existing": existing,
    }


def generate_music(path: Path, duration: float) -> Path:
    """Original instrumental bed. No third-party samples."""
    rng = np.random.default_rng(88)
    n = int(round(duration * SR)) + SR
    t = np.arange(n) / SR
    bpm = 88.0
    beat = 60.0 / bpm
    bar = beat * 4.0

    def energy(ts: np.ndarray) -> np.ndarray:
        e = np.full_like(ts, 0.34)
        e = np.where(ts > 11.5, 0.34 + 0.28 * np.clip((ts - 11.5) / 18.0, 0, 1), e)
        e = np.where(ts > 40.0, 0.62 + 0.30 * np.clip((ts - 40.0) / 18.0, 0, 1), e)
        e = np.where(ts > duration - 2.4, np.clip((duration + 0.2 - ts) / 2.2, 0.08, 1.0) * 0.85, e)
        return e

    env_e = energy(t)
    # Pad: D minor triad spread
    pad = (
        0.045 * np.sin(2 * math.pi * 146.83 * t)
        + 0.035 * np.sin(2 * math.pi * 174.61 * t + 0.2)
        + 0.03 * np.sin(2 * math.pi * 220.00 * t + 0.4)
        + 0.02 * np.sin(2 * math.pi * 293.66 * t + 1.1)
    )
    pad *= (0.75 + 0.25 * np.sin(2 * math.pi * t / 7.5))
    pad *= env_e

    bass = np.zeros(n)
    roots = [36.71, 43.65, 48.99, 32.70]  # D1 A1 B1 C1-ish
    for i, start in enumerate(np.arange(0, duration + bar, bar)):
        note = roots[i % len(roots)]
        sl = slice(int(start * SR), min(n, int((start + bar) * SR)))
        length = sl.stop - sl.start
        if length <= 8:
            continue
        tt = np.arange(length) / SR
        tone = np.sin(2 * math.pi * note * tt) + 0.25 * np.sin(2 * math.pi * note * 2 * tt)
        tone *= _fade(len(tt), int(0.02 * SR), int(0.08 * SR))
        bass[sl] += tone * 0.16
    bass *= env_e

    kick = np.zeros(n)
    snare = np.zeros(n)
    hats = np.zeros(n)
    beat_i = 0
    tt0 = 0.0
    while tt0 < duration + 1:
        i0 = int(tt0 * SR)
        if beat_i % 4 == 0:
            klen = int(0.22 * SR)
            kick[i0 : i0 + klen] += _exp_sweep(klen, 130, 40, SR)[: max(0, n - i0)] * _fade(klen, 4, int(0.18 * SR))[: max(0, n - i0)] * 0.55
        if beat_i % 4 == 2:
            slen = int(0.16 * SR)
            burst = rng.normal(0, 1, slen) * _fade(slen, 3, int(0.12 * SR))
            snare[i0 : i0 + slen] += burst[: max(0, n - i0)] * 0.18
        if env_e[min(i0, n - 1)] > 0.45:
            hlen = int(0.04 * SR)
            hat = rng.normal(0, 1, hlen) * _fade(hlen, 2, hlen - 3)
            hats[i0 : i0 + hlen] += hat[: max(0, n - i0)] * (0.05 + 0.07 * env_e[min(i0, n - 1)])
        beat_i += 1
        tt0 += beat

    # Subtle tick ostinato in the final third
    ticks = np.zeros(n)
    step = beat / 2
    tt0 = 42.0
    while tt0 < duration - 2.0:
        i0 = int(tt0 * SR)
        ln = int(0.03 * SR)
        ticks[i0 : i0 + ln] += rng.normal(0, 1, ln)[: max(0, n - i0)] * _fade(ln, 2, ln - 4)[: max(0, n - i0)] * 0.04
        tt0 += step

    mono = pad + bass + kick * env_e + snare * env_e + hats + ticks
    late = np.pad(mono, (int(0.012 * SR), 0))[:n] * 0.18
    stereo = np.stack([mono + 0.15 * late, mono * 0.92 - 0.12 * late], axis=1)
    peak = np.max(np.abs(stereo))
    stereo *= 0.55 / max(peak, 1e-9)
    write_wav(path, stereo)
    return path


def ffmpeg_frame(ffmpeg: str, video: Path, when: str) -> np.ndarray:
    cmd = [
        ffmpeg, "-v", "error",
        "-sseof" if when == "end" else "-ss",
        "-0.04" if when == "end" else "0.0",
        "-i", str(video),
        "-frames:v", "1",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True)
    frame = np.frombuffer(proc.stdout, dtype=np.uint8)
    return frame.reshape(H, W, 3).copy()


def write_frames_mp4(ffmpeg: str, frames: list[np.ndarray], path: Path) -> None:
    proc = subprocess.Popen(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    assert proc.stdin is not None
    for frame in frames:
        proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed writing {path}")


def zoom_frame(frame: np.ndarray, z: float) -> np.ndarray:
    if z <= 1.001:
        return frame
    nh, nw = int(H * z), int(W * z)
    big = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = (nw - W) // 2
    y = (nh - H) // 2
    return big[y : y + H, x : x + W]


def build_transition(kind: str, last: np.ndarray, nxt: np.ndarray, frames_n: int) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    black = np.zeros_like(last)
    for i in range(frames_n):
        p = i / max(1, frames_n - 1)
        if kind == "dip_black":
            if p < 0.45:
                a = 1.0 - p / 0.45
                img = (last.astype(np.float32) * a).astype(np.uint8)
            elif p > 0.55:
                a = (p - 0.55) / 0.45
                img = (nxt.astype(np.float32) * a).astype(np.uint8)
            else:
                img = black
        elif kind == "hard_impact":
            if i == 0:
                img = (last.astype(np.float32) * 0.35).astype(np.uint8)
            elif i == 1:
                img = np.clip(last.astype(np.float32) * 1.35 + 18, 0, 255).astype(np.uint8)
            else:
                img = nxt
        elif kind == "push":
            x = int(W * p)
            canvas = np.zeros_like(last)
            left = zoom_frame(last, 1.04)
            right = zoom_frame(nxt, 1.04)
            src_w = W - x
            if src_w > 0:
                canvas[:, :src_w] = left[:, x:]
            if x > 0:
                canvas[:, W - x :] = right[:, :x]
            if i > 0:
                canvas = cv2.addWeighted(canvas, 0.72, frames[-1], 0.28, 0)
            img = canvas
        elif kind == "flash":
            if i < 2:
                flash = np.clip(last.astype(np.float32) * 1.25 + 40, 0, 255)
                img = flash.astype(np.uint8)
            else:
                a = (i - 1) / max(1, frames_n - 2)
                img = cv2.addWeighted(last, 1 - a, nxt, a, 0)
        elif kind == "soft_hit":
            z = 1.0 + 0.03 * math.sin(math.pi * p)
            src = last if p < 0.5 else nxt
            img = zoom_frame(src, z)
            if 0.4 < p < 0.7:
                img = cv2.addWeighted(img, 0.85, black, 0.15, 0)
        else:
            img = cv2.addWeighted(last, 1 - p, nxt, p, 0)
        frames.append(img)
    return frames


def duck_envelope(dialogue: np.ndarray, sr: int, attack: float, release: float) -> np.ndarray:
    mono = np.max(np.abs(dialogue), axis=1)
    win = max(1, int(0.01 * sr))
    pad = (win - (mono.size % win)) % win
    chunks = np.pad(mono, (0, pad)).reshape(-1, win).max(axis=1)
    env = np.repeat(chunks, win)[: mono.size]
    atk = math.exp(-1.0 / max(1, attack * sr))
    rel = math.exp(-1.0 / max(1, release * sr))
    out = np.zeros_like(env)
    acc = 0.0
    for i, v in enumerate(env):
        coef = atk if v > acc else rel
        acc = coef * acc + (1.0 - coef) * v
        out[i] = acc
    mx = np.max(out)
    if mx > 1e-6:
        out = np.clip(out / mx, 0, 1)
    return out


def echo_tail(audio: np.ndarray, sr: int, wet: float) -> np.ndarray:
    delays = [int(0.065 * sr), int(0.13 * sr), int(0.21 * sr)]
    gains = [0.42, 0.24, 0.12]
    out = np.zeros((audio.shape[0] + delays[-1] + int(0.35 * sr), 2))
    out[: audio.shape[0]] += audio * 0.15
    for delay, gain in zip(delays, gains):
        sl = slice(delay, delay + audio.shape[0])
        out[sl] += audio * gain * wet
    # short decay pad
    decay = int(0.28 * sr)
    if decay < out.shape[0]:
        out[-decay:] *= np.linspace(1.0, 0.0, decay)[:, None]
    return out


def mix_into(dest: np.ndarray, src: np.ndarray, at: int, gain: float = 1.0) -> None:
    if src.size == 0:
        return
    start = max(0, at)
    skip = start - at
    sl = src[skip:]
    end = min(dest.shape[0], start + sl.shape[0])
    take = end - start
    if take <= 0:
        return
    dest[start:end] += sl[:take] * gain


def probe_duration(ffmpeg: str, path: Path) -> float:
    ffprobe = ffmpeg.replace("ffmpeg.EXE", "ffprobe.EXE").replace("ffmpeg.exe", "ffprobe.exe")
    if not Path(ffprobe).exists():
        ffprobe = "ffprobe"
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(proc.stdout.strip())


def main() -> None:
    if OUT_MP4.resolve() == ORIGINAL_MP4.resolve():
        raise RuntimeError("Refusing to overwrite the original summary MP4")
    orig_hash = sha256_file(ORIGINAL_MP4) if ORIGINAL_MP4.exists() else ""
    orig_size = ORIGINAL_MP4.stat().st_size if ORIGINAL_MP4.exists() else 0
    print(f"[lock] original summary sha256={orig_hash} size={orig_size}", flush=True)

    source = read_json(SOURCE_PLAN)
    trailer = read_json(TRAILER_PLAN)
    lock_editorial(source, trailer)
    cfg = load_config(ROOT)
    ffmpeg = require_binary("ffmpeg")
    src_video = _resolve_source_video(Path(source["source_video"]), SOURCE_PLAN)
    profile = resolve_framing_profile(src_video, cfg)
    if profile is None:
        raise FileNotFoundError("Frozen CFS03 framing profile is required")
    rcfg = dict(cfg["render"])
    rcfg["burn_captions"] = False
    layout = layout_from_framing_profile(profile, rcfg, stack_order=STACK)
    if layout.top is None or layout.middle is None or layout.bottom is None:
        raise RuntimeError("Stacked layout missing")
    if (round(layout.top.x), round(layout.top.y)) != (52, 24):
        raise RuntimeError("TOP must be speaker_a crop")
    if (round(layout.middle.x), round(layout.middle.y)) != (512, 552):
        raise RuntimeError("MIDDLE must be speaker_c crop")
    if (round(layout.bottom.x), round(layout.bottom.y)) != (972, 24):
        raise RuntimeError("BOTTOM must be speaker_b crop")

    treatments = {row["segment_index"]: row for row in trailer["clip_treatments"]}
    transitions = trailer["transitions"]
    echo_by = {row["after_segment_index"]: row for row in trailer["echo"]}
    tail_s = float(trailer["ending_tail_s"])
    mix_cfg = trailer["mix"]

    ASSETS.mkdir(parents=True, exist_ok=True)
    sfx_paths = generate_sfx(ASSETS)
    sfx_audio = {}
    for key, path in sfx_paths.items():
        if not path.is_file():
            continue
        data, sr = read_wav(path)
        sfx_audio[key] = resample_stereo(data, sr, SR)

    with tempfile.TemporaryDirectory(prefix="cfs03_trailer_") as td:
        temp = Path(td)
        clips = []
        for idx, seg in enumerate(source["segments"], start=1):
            start = parse_timestamp(seg["start"])
            end = parse_timestamp(seg["end"])
            raw = temp / f"raw_{idx:02d}.mp4"
            before, after = _accurate_cut_args(start, end)
            run([
                ffmpeg, "-y",
                *before, "-i", str(src_video), *after,
                "-filter_complex", layout.filter_complex,
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-r", str(FPS),
                str(raw),
            ])
            treat = treatments[idx]
            vf = ["scale=1080:1920", "setsar=1"]
            dur = end - start
            if treat.get("start_punch"):
                vf.append("eq=brightness='if(lt(n,4),0.045,0)':eval=frame")
            if treat.get("end_fade"):
                vf.append(f"fade=t=out:st={max(0.0, dur - 0.11):.3f}:d=0.11")
            if idx > 1:
                vf.append("fade=t=in:d=0.06")
            treated = temp / f"clip_{idx:02d}.mp4"
            run([
                ffmpeg, "-y", "-i", str(raw),
                "-vf", ",".join(vf),
                "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                str(treated),
            ])
            wav = temp / f"clip_{idx:02d}.wav"
            run([
                ffmpeg, "-y", "-i", str(raw),
                "-vn", "-ac", "2", "-ar", str(SR),
                "-c:a", "pcm_s16le",
                str(wav),
            ])
            audio, sr = read_wav(wav)
            audio = resample_stereo(audio, sr, SR)
            need = int(round(dur * SR))
            if audio.shape[0] >= need:
                audio = audio[:need]
            else:
                audio = np.pad(audio, ((0, need - audio.shape[0]), (0, 0)))
            clips.append({
                "index": idx,
                "video": treated,
                "audio": audio,
                "duration": dur,
                "seg": seg,
            })
            print(f"[trailer] clip {idx} {seg['start']}-{seg['end']} {dur:.3f}s {seg['role']}", flush=True)

        # Build video sequence: clip + transition + clip...
        trans_videos = []
        for spec in transitions:
            a, b = spec["between"]
            last = ffmpeg_frame(ffmpeg, clips[a - 1]["video"], "end")
            nxt = ffmpeg_frame(ffmpeg, clips[b - 1]["video"], "start")
            nfr = max(3, int(round(spec["duration_ms"] * FPS / 1000.0)))
            frames = build_transition(spec["type"], last, nxt, nfr)
            path = temp / f"trans_{a}_{b}.mp4"
            write_frames_mp4(ffmpeg, frames, path)
            trans_videos.append((spec, path, nfr / FPS))
            print(f"[trailer] transition {a}->{b} {spec['type']} {nfr}f {spec['duration_ms']}ms", flush=True)

        # Ending tail from last frame
        last = ffmpeg_frame(ffmpeg, clips[-1]["video"], "end")
        tail_n = int(round(tail_s * FPS))
        tail_frames = []
        for i in range(tail_n):
            p = i / max(1, tail_n - 1)
            z = 1.0 + 0.02 * p
            img = zoom_frame(last, z)
            fade = 1.0 if p < 0.45 else max(0.0, 1.0 - (p - 0.45) / 0.55)
            img = (img.astype(np.float32) * fade).astype(np.uint8)
            tail_frames.append(img)
        tail_path = temp / "tail.mp4"
        write_frames_mp4(ffmpeg, tail_frames, tail_path)

        concat_list = temp / "vconcat.txt"
        lines = []
        for i, clip in enumerate(clips):
            lines.append(f"file '{clip['video'].as_posix()}'")
            if i < len(trans_videos):
                lines.append(f"file '{trans_videos[i][1].as_posix()}'")
        lines.append(f"file '{tail_path.as_posix()}'")
        concat_list.write_text("\n".join(lines), encoding="utf-8")
        joined = temp / "joined_v.mp4"
        run([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-an",
            str(joined),
        ])

        # Audio timeline
        trans_durs = [row[2] for row in trans_videos]
        total_s = sum(c["duration"] for c in clips) + sum(trans_durs) + tail_s
        music_path = ASSETS / "cfs03_trailer_bed.wav"
        generate_music(music_path, total_s + 0.8)
        music, msr = read_wav(music_path)
        music = resample_stereo(music, msr, SR)

        n_samples = int(round(total_s * SR)) + int(0.4 * SR)
        dialogue = np.zeros((n_samples, 2))
        sfx_bus = np.zeros((n_samples, 2))
        echo_bus = np.zeros((n_samples, 2))
        cursor = 0.0
        placements = []
        for i, clip in enumerate(clips):
            at = int(round(cursor * SR))
            mix_into(dialogue, clip["audio"], at, 1.0)
            placements.append((clip["index"], cursor, cursor + clip["duration"]))
            echo_spec = echo_by.get(clip["index"])
            if echo_spec:
                send_n = int(echo_spec["send_s"] * SR)
                send = clip["audio"][-send_n:]
                tail = echo_tail(send, SR, float(echo_spec["wet"]))
                mix_into(echo_bus, tail, at + clip["audio"].shape[0] - send_n, 1.0)
            cursor += clip["duration"]
            if i < len(trans_videos):
                spec, _path, td_s = trans_videos[i]
                sfx_key = spec["sfx"]
                if sfx_key in sfx_audio:
                    lead = 0.03 if spec["type"] != "riser" else max(0.0, 1.15 - td_s)
                    mix_into(sfx_bus, sfx_audio[sfx_key], int(round((cursor - lead) * SR)), 0.55)
                cursor += td_s
        # ending impact
        if "impact_low" in sfx_audio:
            mix_into(sfx_bus, sfx_audio["impact_low"], int(round((cursor - 0.05) * SR)), 0.5)
        if "bass_pulse" in sfx_audio:
            mix_into(sfx_bus, sfx_audio["bass_pulse"], int(round(cursor * SR)), 0.4)

        env = duck_envelope(dialogue, SR, mix_cfg["duck_attack_s"], mix_cfg["duck_release_s"])
        under = float(mix_cfg["music_under_speech"])
        gaps = float(mix_cfg["music_in_gaps"])
        gain = under + (gaps - under) * (1.0 - env) ** 1.35
        music_cut = music[:n_samples]
        if music_cut.shape[0] < n_samples:
            music_cut = np.pad(music_cut, ((0, n_samples - music_cut.shape[0]), (0, 0)))
        ducked = music_cut * gain[:, None]
        mixed = dialogue * 1.0 + echo_bus * 0.9 + sfx_bus * 0.85 + ducked
        ceiling = float(mix_cfg["limiter_ceiling"])
        peak = np.max(np.abs(mixed))
        if peak > ceiling:
            mixed *= ceiling / peak
        # soft limiter
        mixed = np.tanh(mixed * 1.05) / math.tanh(1.05)
        mixed *= 0.98
        mix_wav = temp / "mix.wav"
        write_wav(mix_wav, mixed[: int(round(total_s * SR))])

        OUT_MP4.parent.mkdir(parents=True, exist_ok=True)
        run([
            ffmpeg, "-y",
            "-i", str(joined),
            "-i", str(mix_wav),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(OUT_MP4),
        ])

    after_hash = sha256_file(ORIGINAL_MP4)
    after_size = ORIGINAL_MP4.stat().st_size
    if after_hash != orig_hash or after_size != orig_size:
        raise RuntimeError("Original summary MP4 was modified — abort")
    dur = probe_duration(ffmpeg, OUT_MP4)
    print(f"[trailer] wrote {OUT_MP4} duration={dur:.3f}s", flush=True)
    print(f"[lock] original summary unchanged sha256={after_hash}", flush=True)


if __name__ == "__main__":
    main()
