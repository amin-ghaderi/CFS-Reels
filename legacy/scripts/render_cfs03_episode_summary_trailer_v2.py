# CFS03 trailer V2: identical V1 picture, new louder original score and SFX.
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import numpy as np

from reels_factory.render import _accurate_cut_args, _resolve_source_video
from reels_factory.utils import parse_timestamp, read_json, require_binary, run

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_cfs03_episode_summary_trailer as v1  # noqa: E402

SOURCE_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01.json"
TRAILER_V1_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01_trailer.json"
TRAILER_V2_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01_trailer_v2.json"
ORIGINAL_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01.mp4"
V1_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer.mp4"
OUT_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer_v2.mp4"
ASSETS = ROOT / "data" / "episode_summaries" / "trailer_assets"
SR = 48000
FPS = 30
BPM = 98


def generate_music_v2(path: Path, duration: float) -> Path:
    rng = np.random.default_rng(98)
    n = int(round(duration * SR)) + SR
    t = np.arange(n) / SR
    beat = 60.0 / BPM
    bar = beat * 4.0

    def energy(ts: np.ndarray) -> np.ndarray:
        e = np.full_like(ts, 0.28)
        e = np.where(ts > 8.0, 0.28 + 0.32 * np.clip((ts - 8.0) / 16.0, 0, 1), e)
        e = np.where(ts > 28.0, 0.60 + 0.22 * np.clip((ts - 28.0) / 16.0, 0, 1), e)
        e = np.where(ts > 48.0, 0.82 + 0.18 * np.clip((ts - 48.0) / 14.0, 0, 1), e)
        e = np.where(ts > duration - 2.6, np.clip((duration + 0.15 - ts) / 2.4, 0.12, 1.0), e)
        return e

    env_e = energy(t)

    # Dark pad / tension synths (D minor / F)
    pad = (
        0.07 * np.sin(2 * math.pi * 73.42 * t)
        + 0.05 * np.sin(2 * math.pi * 110.00 * t + 0.3)
        + 0.04 * np.sin(2 * math.pi * 146.83 * t + 0.8)
        + 0.03 * np.sin(2 * math.pi * 174.61 * t + 1.4)
        + 0.02 * np.sin(2 * math.pi * 220.00 * t * 1.003)
    )
    pad *= 0.7 + 0.3 * np.sin(2 * math.pi * t / 5.5)
    pad *= env_e

    # Pulse bass
    bass = np.zeros(n)
    roots = [36.71, 32.70, 41.20, 29.14]  # D C E Bb
    for i, start in enumerate(np.arange(0, duration + bar, bar)):
        sl = slice(int(start * SR), min(n, int((start + bar) * SR)))
        length = sl.stop - sl.start
        if length <= 16:
            continue
        tt = np.arange(length) / SR
        note = roots[i % len(roots)]
        tone = np.sin(2 * math.pi * note * tt) + 0.35 * np.sin(2 * math.pi * note * 2 * tt)
        tone += 0.08 * np.sin(2 * math.pi * note * 3 * tt)
        tone *= v1._fade(length, int(0.01 * SR), int(0.06 * SR))
        bass[sl] += tone * 0.28
    bass *= env_e

    kick = np.zeros(n)
    snare = np.zeros(n)
    hats = np.zeros(n)
    beat_i = 0
    tt0 = 0.0
    while tt0 < duration + 1:
        i0 = int(tt0 * SR)
        e_here = float(env_e[min(i0, n - 1)])
        # Open: half-time. Build: every beat. Final third: every beat + extra click.
        do_kick = (beat_i % 2 == 0) if e_here < 0.5 else True
        if do_kick:
            klen = int(0.2 * SR)
            chunk = v1._exp_sweep(klen, 150, 36, SR) * v1._fade(klen, 3, int(0.16 * SR))
            take = min(klen, n - i0)
            if take > 0:
                kick[i0 : i0 + take] += chunk[:take] * (0.62 + 0.28 * e_here)
        if beat_i % 2 == 1 and e_here > 0.42:
            slen = int(0.14 * SR)
            burst = rng.normal(0, 1, slen) * v1._fade(slen, 2, int(0.1 * SR))
            take = min(slen, n - i0)
            if take > 0:
                snare[i0 : i0 + take] += burst[:take] * (0.16 + 0.12 * e_here)
        if e_here > 0.38:
            hlen = int(0.028 * SR)
            hat = rng.normal(0, 1, hlen) * v1._fade(hlen, 1, hlen - 2)
            take = min(hlen, n - i0)
            if take > 0:
                hats[i0 : i0 + take] += hat[:take] * (0.06 + 0.08 * e_here)
            if e_here > 0.78 and beat_i % 1 == 0:
                i1 = i0 + int(0.5 * beat * SR)
                if i1 < n:
                    hats[i1 : i1 + take] += hat[:take] * 0.05
        beat_i += 1
        tt0 += beat

    # Electronic ticks in the last third
    ticks = np.zeros(n)
    tt0 = 46.0
    while tt0 < duration - 2.2:
        i0 = int(tt0 * SR)
        ln = int(0.018 * SR)
        take = min(ln, n - i0)
        if take > 0:
            ticks[i0 : i0 + take] += rng.normal(0, 1, take) * v1._fade(take, 1, take - 2) * 0.055
        tt0 += beat / 2

    drone = 0.04 * np.sin(2 * math.pi * 49.00 * t) * env_e
    mono = pad + bass + kick + snare + hats + ticks + drone
    late = np.pad(mono, (int(0.011 * SR), 0))[:n] * 0.22
    stereo = np.stack([mono + 0.2 * late, mono * 0.9 - 0.16 * late], axis=1)
    peak = np.max(np.abs(stereo))
    stereo *= 0.72 / max(peak, 1e-9)
    v1.write_wav(path, stereo)
    return path


def generate_sfx_v2(assets: Path) -> dict[str, Path]:
    rng = np.random.default_rng(7)

    def stereo(mono: np.ndarray, width: float = 0.1) -> np.ndarray:
        late = np.pad(mono, (int(0.001 * SR), 0))[: mono.shape[0]] * width
        left = mono + late
        right = mono - late
        peak = max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-9)
        g = 0.92 / peak
        return np.stack([left * g, right * g], axis=1)

    n_boom = int(0.55 * SR)
    boom = v1._exp_sweep(n_boom, 90, 28, SR) * v1._fade(n_boom, 6, int(0.45 * SR))
    boom += rng.normal(0, 1, n_boom) * v1._fade(n_boom, 4, int(0.08 * SR)) * 0.08
    boom_path = assets / "sfx_v2_boom.wav"
    v1.write_wav(boom_path, stereo(boom * 0.85, 0.03))

    n_sub = int(0.32 * SR)
    sub = v1._exp_sweep(n_sub, 70, 26, SR) * v1._fade(n_sub, 4, int(0.26 * SR))
    sub_path = assets / "sfx_v2_sub_drop.wav"
    v1.write_wav(sub_path, stereo(sub * 0.9, 0.02))

    n_down = int(0.7 * SR)
    down = v1._exp_sweep(n_down, 380, 70, SR) * np.linspace(1.0, 0.15, n_down)
    air = rng.normal(0, 1, n_down)
    air = np.convolve(air, np.ones(24) / 24, mode="same") * np.linspace(0.4, 0.05, n_down)
    downer = (down * 0.35 + air) * v1._fade(n_down, int(0.02 * SR), int(0.18 * SR))
    down_path = assets / "sfx_v2_downer.wav"
    v1.write_wav(down_path, stereo(downer, 0.16))

    n_sw = int(0.28 * SR)
    sw = rng.normal(0, 1, n_sw)
    sw = np.convolve(sw, np.ones(36) / 36, mode="same") * np.linspace(0.15, 1.0, n_sw)
    sw *= v1._fade(n_sw, int(0.02 * SR), int(0.12 * SR))
    sw_path = assets / "sfx_v2_sweep.wav"
    v1.write_wav(sw_path, stereo(sw * 0.6, 0.2))

    n_rev = int(0.18 * SR)
    rev = np.flip(np.convolve(rng.normal(0, 1, n_rev), np.ones(28) / 28, mode="same"))
    rev *= v1._fade(n_rev, int(0.02 * SR), int(0.05 * SR)) * np.linspace(0.2, 1.0, n_rev)
    rev_path = assets / "sfx_v2_reverse_swell.wav"
    v1.write_wav(rev_path, stereo(rev * 0.55, 0.14))

    return {
        "boom": boom_path,
        "sub_drop": sub_path,
        "downer": down_path,
        "sweep": sw_path,
        "reverse_swell": rev_path,
    }


def echo_tail_v2(audio: np.ndarray, sr: int, wet: float) -> np.ndarray:
    delays = [int(0.07 * sr), int(0.14 * sr), int(0.23 * sr), int(0.34 * sr)]
    gains = [0.5, 0.32, 0.18, 0.1]
    extra = delays[-1] + int(0.55 * sr)
    out = np.zeros((audio.shape[0] + extra, 2))
    out[: audio.shape[0]] += audio * 0.12
    for delay, gain in zip(delays, gains):
        sl = slice(delay, delay + audio.shape[0])
        out[sl] += audio * gain * wet
    decay = int(0.42 * sr)
    if decay < out.shape[0]:
        out[-decay:] *= np.linspace(1.0, 0.0, decay)[:, None]
    return out


def trans_seconds(ms: int) -> float:
    return max(3, int(round(ms * FPS / 1000.0))) / FPS


def load_sfx_bank() -> dict[str, np.ndarray]:
    bank = {}
    v2_paths = generate_sfx_v2(ASSETS)
    extra = {
        "whoosh_short": ASSETS / "sfx_whoosh_short.wav",
        "whoosh_reverse": ASSETS / "sfx_whoosh_reverse.wav",
        "impact_low": ASSETS / "sfx_impact_low.wav",
        "hit_soft": ASSETS / "sfx_hit_soft.wav",
        "riser": ASSETS / "sfx_riser.wav",
        "bass_pulse": ASSETS / "sfx_bass_pulse.wav",
        "whoosh_existing": ROOT / "assets" / "sounds" / "whoosh_soft.wav",
        **v2_paths,
    }
    for key, path in extra.items():
        if not path.is_file():
            continue
        data, sr = v1.read_wav(path)
        bank[key] = v1.resample_stereo(data, sr, SR)
    return bank


def main() -> None:
    if OUT_MP4.resolve() in {ORIGINAL_MP4.resolve(), V1_MP4.resolve()}:
        raise RuntimeError("Refusing to overwrite locked summary/trailer files")
    orig_hash = v1.sha256_file(ORIGINAL_MP4)
    v1_hash = v1.sha256_file(V1_MP4)
    orig_size = ORIGINAL_MP4.stat().st_size
    v1_size = V1_MP4.stat().st_size
    print(f"[lock] summary sha256={orig_hash}", flush=True)
    print(f"[lock] trailer v1 sha256={v1_hash}", flush=True)

    source = read_json(SOURCE_PLAN)
    v1_plan = read_json(TRAILER_V1_PLAN)
    v2_plan = read_json(TRAILER_V2_PLAN)
    if len(source["segments"]) != 8:
        raise ValueError("Expected 8 excerpts")
    if list(v1_plan["stack_order"]) != ["speaker_a", "speaker_c", "speaker_b"]:
        raise ValueError("V1 stack must stay A/C/B")
    for a, b in zip(v1_plan["transitions"], v2_plan["transitions"]):
        if a["between"] != b["between"] or a["type"] != b["type"] or a["duration_ms"] != b["duration_ms"]:
            raise ValueError("V2 must keep V1 visual transition structure")

    ffmpeg = require_binary("ffmpeg")
    src_video = _resolve_source_video(Path(source["source_video"]), SOURCE_PLAN)
    mix_cfg = v2_plan["mix"]
    tail_s = float(v2_plan["ending_tail_s"])
    echo_by = {row["after_segment_index"]: row for row in v2_plan["echo"]}
    sfx = load_sfx_bank()

    trans_durs = [trans_seconds(row["duration_ms"]) for row in v2_plan["transitions"]]
    clip_durs = [
        parse_timestamp(seg["end"]) - parse_timestamp(seg["start"])
        for seg in source["segments"]
    ]
    total_s = sum(clip_durs) + sum(trans_durs) + tail_s
    video_s = v1.probe_duration(ffmpeg, V1_MP4)

    music_path = ASSETS / "cfs03_trailer_bed_v2.wav"
    generate_music_v2(music_path, max(total_s, video_s) + 1.0)
    music, msr = v1.read_wav(music_path)
    music = v1.resample_stereo(music, msr, SR)

    with tempfile.TemporaryDirectory(prefix="cfs03_trailer_v2_") as td:
        temp = Path(td)
        clips_audio = []
        for idx, seg in enumerate(source["segments"], start=1):
            start = parse_timestamp(seg["start"])
            end = parse_timestamp(seg["end"])
            dur = end - start
            wav = temp / f"dlg_{idx:02d}.wav"
            before, after = _accurate_cut_args(start, end)
            run([
                ffmpeg, "-y",
                *before, "-i", str(src_video), *after,
                "-vn", "-ac", "2", "-ar", str(SR),
                "-c:a", "pcm_s16le",
                str(wav),
            ])
            audio, sr = v1.read_wav(wav)
            audio = v1.resample_stereo(audio, sr, SR)
            need = int(round(dur * SR))
            if audio.shape[0] >= need:
                audio = audio[:need]
            else:
                audio = np.pad(audio, ((0, need - audio.shape[0]), (0, 0)))
            clips_audio.append(audio)
            print(f"[v2] dialogue {idx} {dur:.3f}s", flush=True)

        n_samples = int(round(max(total_s, video_s) * SR)) + int(0.5 * SR)
        dialogue = np.zeros((n_samples, 2))
        sfx_bus = np.zeros((n_samples, 2))
        echo_bus = np.zeros((n_samples, 2))
        cursor = 0.0
        clip_starts = []
        for i, audio in enumerate(clips_audio):
            idx = i + 1
            at = int(round(cursor * SR))
            clip_starts.append(cursor)
            v1.mix_into(dialogue, audio, at, 1.0)
            echo_spec = echo_by.get(idx)
            if echo_spec:
                send_n = int(echo_spec["send_s"] * SR)
                send = audio[-send_n:]
                tail = echo_tail_v2(send, SR, float(echo_spec["wet"]))
                v1.mix_into(echo_bus, tail, at + audio.shape[0] - send_n, 1.0)
            cursor += clip_durs[i]
            if i < len(v2_plan["transitions"]):
                spec = v2_plan["transitions"][i]
                td_s = trans_durs[i]
                for sfx_key in spec["sfx"]:
                    if sfx_key not in sfx:
                        continue
                    lead = 0.04
                    if sfx_key == "riser":
                        lead = max(0.0, 1.12 - td_s)
                    if sfx_key == "downer":
                        lead = 0.12
                    gain = 0.78 if sfx_key in {"whoosh_existing", "whoosh_short"} else 0.9
                    v1.mix_into(sfx_bus, sfx[sfx_key], int(round((cursor - lead) * SR)), gain)
                cursor += td_s

        for acc in v2_plan["dialogue_accents"]:
            si = acc["segment_index"]
            t0 = clip_starts[si - 1] + float(acc["at_s"])
            kind = acc["type"]
            key = {
                "reverse_swell": "reverse_swell",
                "bass_pulse": "bass_pulse",
                "impact": "impact_low",
                "boom": "boom",
            }[kind]
            gain = 0.42 if kind in {"reverse_swell", "bass_pulse"} else 0.5
            if key in sfx:
                v1.mix_into(sfx_bus, sfx[key], int(round(t0 * SR)), gain)
                print(f"[v2] accent seg {si} t={t0:.2f} {kind}", flush=True)

        # Ending hit
        end_at = sum(clip_durs) + sum(trans_durs)
        if "boom" in sfx:
            v1.mix_into(sfx_bus, sfx["boom"], int(round((end_at - 0.04) * SR)), 0.72)
        if "sub_drop" in sfx:
            v1.mix_into(sfx_bus, sfx["sub_drop"], int(round(end_at * SR)), 0.65)

        env = v1.duck_envelope(
            dialogue, SR, mix_cfg["duck_attack_s"], mix_cfg["duck_release_s"]
        )
        under = float(mix_cfg["music_under_speech"])
        gaps = float(mix_cfg["music_in_gaps"])
        gain = under + (gaps - under) * (1.0 - env) ** 1.2
        music_cut = music[:n_samples]
        if music_cut.shape[0] < n_samples:
            music_cut = np.pad(music_cut, ((0, n_samples - music_cut.shape[0]), (0, 0)))
        ducked = music_cut * gain[:, None]
        mixed = (
            dialogue * float(mix_cfg["dialogue_gain"])
            + echo_bus * float(mix_cfg["echo_gain"])
            + sfx_bus * float(mix_cfg["sfx_gain"])
            + ducked
        )
        # Light dialogue-preserving limiter (no tanh squash)
        ceiling = float(mix_cfg["limiter_ceiling"])
        peak = np.max(np.abs(mixed))
        if peak > ceiling:
            mixed *= ceiling / peak
        over = np.abs(mixed) > 0.9
        if np.any(over):
            mixed = np.where(over, np.tanh(mixed), mixed)
        mixed *= 0.99
        target_n = int(round(video_s * SR))
        if mixed.shape[0] >= target_n:
            mixed = mixed[:target_n]
        else:
            mixed = np.pad(mixed, ((0, target_n - mixed.shape[0]), (0, 0)))
        mix_wav = temp / "mix_v2.wav"
        v1.write_wav(mix_wav, mixed)
        mix_ln = temp / "mix_v2_ln.wav"
        target = float(mix_cfg.get("target_lufs", -14))
        run([
            ffmpeg, "-y", "-i", str(mix_wav),
            "-af", f"loudnorm=I={target}:TP=-1.2:LRA=11",
            str(mix_ln),
        ])

        OUT_MP4.parent.mkdir(parents=True, exist_ok=True)
        run([
            ffmpeg, "-y",
            "-i", str(V1_MP4),
            "-i", str(mix_ln),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(OUT_MP4),
        ])

    if v1.sha256_file(ORIGINAL_MP4) != orig_hash or ORIGINAL_MP4.stat().st_size != orig_size:
        raise RuntimeError("Original summary MP4 changed")
    if v1.sha256_file(V1_MP4) != v1_hash or V1_MP4.stat().st_size != v1_size:
        raise RuntimeError("V1 trailer MP4 changed")
    dur = v1.probe_duration(ffmpeg, OUT_MP4)
    print(f"[v2] wrote {OUT_MP4} duration={dur:.3f}s", flush=True)
    print(f"[lock] summary unchanged; v1 trailer unchanged", flush=True)


if __name__ == "__main__":
    main()
