# CFS03 trailer V3: identical V1 picture, high-energy original mix.
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
import render_cfs03_episode_summary_trailer_v2 as v2  # noqa: E402

SOURCE_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01.json"
V1_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01_trailer.json"
V3_PLAN = ROOT / "data" / "episode_summaries" / "CFS03_summary_01_trailer_v3.json"
ORIGINAL_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01.mp4"
V1_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer.mp4"
V2_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer_v2.mp4"
OUT_MP4 = ROOT / "data" / "output" / "CFS03_summary" / "CFS03_episode_summary_01_trailer_v3.mp4"
ASSETS = ROOT / "data" / "episode_summaries" / "trailer_assets"
SR = 48000
FPS = 30
BPM = 100


def _hp(x: np.ndarray) -> np.ndarray:
    y = np.zeros_like(x)
    y[1:] = x[1:] - x[:-1]
    return y


def generate_music_v3(path: Path, duration: float) -> Path:
    rng = np.random.default_rng(100)
    n = int(round(duration * SR)) + SR
    t = np.arange(n) / SR
    beat = 60.0 / BPM

    def energy(ts: np.ndarray) -> np.ndarray:
        e = np.full_like(ts, 0.78)
        e = np.where(ts > 10.0, 0.78 + 0.12 * np.clip((ts - 10.0) / 18.0, 0, 1), e)
        e = np.where(ts > 32.0, 0.90 + 0.10 * np.clip((ts - 32.0) / 16.0, 0, 1), e)
        e = np.where(ts > 50.0, 1.0, e)
        e = np.where(ts > duration - 2.4, np.clip((duration + 0.1 - ts) / 2.3, 0.18, 1.0), e)
        return e

    env_e = energy(t)

    pad = (
        0.05 * np.sin(2 * math.pi * 73.42 * t)
        + 0.04 * np.sin(2 * math.pi * 110.0 * t + 0.4)
        + 0.035 * np.sin(2 * math.pi * 146.83 * t + 0.9)
        + 0.025 * np.sin(2 * math.pi * 196.0 * t + 0.2)
        + 0.02 * np.sin(2 * math.pi * 293.66 * t * 1.004)
    )
    pad *= 1.35 * (0.65 + 0.35 * np.sin(2 * math.pi * t / 4.8))
    pad *= env_e

    bass = np.zeros(n)
    roots = [49.00, 43.65, 36.71, 41.20]
    bar = beat * 4
    for i, start in enumerate(np.arange(0, duration + bar, bar)):
        sl = slice(int(start * SR), min(n, int((start + bar) * SR)))
        length = sl.stop - sl.start
        if length <= 16:
            continue
        tt = np.arange(length) / SR
        note = roots[i % len(roots)]
        tone = np.sin(2 * math.pi * note * tt)
        tone += 0.45 * np.sin(2 * math.pi * note * 2 * tt)
        tone += 0.18 * np.sin(2 * math.pi * note * 3 * tt)
        # audible mid-bass presence
        tone += 0.12 * np.sin(2 * math.pi * note * 4 * tt)
        tone *= v1._fade(length, int(0.008 * SR), int(0.05 * SR))
        bass[sl] += tone * 0.42
    bass *= env_e

    kick = np.zeros(n)
    snare = np.zeros(n)
    hats = np.zeros(n)
    beat_i = 0
    tt0 = 0.0
    while tt0 < duration + 1:
        i0 = int(tt0 * SR)
        e_here = float(env_e[min(max(i0, 0), n - 1)])
        klen = int(0.18 * SR)
        body = v1._exp_sweep(klen, 170, 42, SR) * v1._fade(klen, 2, int(0.14 * SR))
        click_n = int(0.012 * SR)
        click = _hp(rng.normal(0, 1, klen))
        click[:click_n] *= v1._fade(click_n, 1, click_n - 2) if click_n > 3 else 1
        click[click_n:] *= 0.08
        k = body * 0.85 + click * 1.15
        take = min(klen, n - i0)
        if take > 0:
            kick[i0 : i0 + take] += k[:take] * (0.85 + 0.15 * e_here)
        if beat_i % 2 == 1:
            slen = int(0.11 * SR)
            burst = _hp(rng.normal(0, 1, slen)) * v1._fade(slen, 2, int(0.08 * SR))
            take = min(slen, n - i0)
            if take > 0:
                snare[i0 : i0 + take] += burst[:take] * (0.42 + 0.16 * e_here)
        hlen = int(0.022 * SR)
        hat = _hp(rng.normal(0, 1, hlen)) * v1._fade(hlen, 1, hlen - 2)
        take = min(hlen, n - i0)
        if take > 0:
            hats[i0 : i0 + take] += hat[:take] * (0.55 + 0.18 * e_here)
        i1 = i0 + int(0.5 * beat * SR)
        if i1 < n and e_here > 0.7:
            hats[i1 : i1 + take] += hat[:take] * 0.32
        beat_i += 1
        tt0 += beat

    ticks = np.zeros(n)
    tt0 = 0.0
    while tt0 < duration - 2.0:
        i0 = int(tt0 * SR)
        ln = int(0.014 * SR)
        take = min(ln, n - i0)
        if take > 0:
            ticks[i0 : i0 + take] += rng.normal(0, 1, take) * v1._fade(take, 1, take - 2) * 0.08
        tt0 += beat / 2

    mono = pad + bass + kick + snare + hats + ticks
    late = np.pad(mono, (int(0.008 * SR), 0))[:n] * 0.18
    stereo = np.stack([mono + 0.16 * late, mono * 0.92 - 0.12 * late], axis=1)
    peak = np.max(np.abs(stereo))
    stereo *= 0.89 / max(peak, 1e-9)
    v1.write_wav(path, stereo)
    return path


def generate_click_impact(path: Path) -> Path:
    rng = np.random.default_rng(3)
    n = int(0.22 * SR)
    body = v1._exp_sweep(n, 200, 50, SR) * v1._fade(n, 2, int(0.16 * SR))
    click = _hp(rng.normal(0, 1, n)) * v1._fade(n, 1, int(0.04 * SR))
    mono = body * 0.7 + click * 0.85
    late = np.pad(mono, (40, 0))[:n] * 0.08
    stereo = np.stack([mono + late, mono - late], axis=1)
    peak = np.max(np.abs(stereo))
    stereo *= 0.95 / max(peak, 1e-9)
    v1.write_wav(path, stereo)
    return path


def echo_tail_v3(audio: np.ndarray, sr: int, wet: float) -> np.ndarray:
    delays = [int(0.08 * sr), int(0.16 * sr), int(0.26 * sr), int(0.4 * sr)]
    gains = [0.62, 0.4, 0.24, 0.14]
    extra = delays[-1] + int(0.7 * sr)
    out = np.zeros((audio.shape[0] + extra, 2))
    out[: audio.shape[0]] += audio * 0.08
    for delay, gain in zip(delays, gains):
        out[delay : delay + audio.shape[0]] += audio * gain * wet
    decay = int(0.5 * sr)
    out[-decay:] *= np.linspace(1.0, 0.0, decay)[:, None]
    return out


def trans_seconds(ms: int) -> float:
    return max(3, int(round(ms * FPS / 1000.0))) / FPS


def smooth_gain(g: np.ndarray, sr: int, attack: float, release: float) -> np.ndarray:
    atk = math.exp(-1.0 / max(1, attack * sr))
    rel = math.exp(-1.0 / max(1, release * sr))
    out = np.zeros_like(g)
    acc = g[0]
    for i, v in enumerate(g):
        coef = atk if v < acc else rel
        acc = coef * acc + (1.0 - coef) * v
        out[i] = acc
    return out


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2) + 1e-20))


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def load_bank() -> dict[str, np.ndarray]:
    click_path = generate_click_impact(ASSETS / "sfx_v3_click_impact.wav")
    bank = v2.load_sfx_bank()
    data, sr = v1.read_wav(click_path)
    bank["click_impact"] = v1.resample_stereo(data, sr, SR)
    return bank


def peak_normalize(x: np.ndarray, peak_db: float) -> np.ndarray:
    p = np.max(np.abs(x))
    if p < 1e-9:
        return x
    return x * (db_to_lin(peak_db) / p)


def main() -> None:
    if OUT_MP4.resolve() in {ORIGINAL_MP4.resolve(), V1_MP4.resolve(), V2_MP4.resolve()}:
        raise RuntimeError("Refusing to overwrite locked files")
    h_sum = v1.sha256_file(ORIGINAL_MP4)
    h_v1 = v1.sha256_file(V1_MP4)
    h_v2 = v1.sha256_file(V2_MP4)
    print(f"[lock] summary={h_sum}", flush=True)
    print(f"[lock] v1={h_v1}", flush=True)
    print(f"[lock] v2={h_v2}", flush=True)

    source = read_json(SOURCE_PLAN)
    v1_plan = read_json(V1_PLAN)
    v3 = read_json(V3_PLAN)
    for a, b in zip(v1_plan["transitions"], v3["transitions"]):
        if a["between"] != b["between"] or a["type"] != b["type"] or a["duration_ms"] != b["duration_ms"]:
            raise ValueError("V3 must keep V1 visual transition structure")

    ffmpeg = require_binary("ffmpeg")
    src_video = _resolve_source_video(Path(source["source_video"]), SOURCE_PLAN)
    tail_s = float(v3["ending_tail_s"])
    echo_by = {row["after_segment_index"]: row for row in v3["echo"]}
    sfx = load_bank()
    mix_cfg = v3["mix"]

    trans_durs = [trans_seconds(row["duration_ms"]) for row in v3["transitions"]]
    clip_durs = [
        parse_timestamp(seg["end"]) - parse_timestamp(seg["start"])
        for seg in source["segments"]
    ]
    total_s = sum(clip_durs) + sum(trans_durs) + tail_s
    video_s = v1.probe_duration(ffmpeg, V1_MP4)

    music_path = ASSETS / "cfs03_trailer_bed_v3.wav"
    generate_music_v3(music_path, max(total_s, video_s) + 1.0)
    music, msr = v1.read_wav(music_path)
    music = v1.resample_stereo(music, msr, SR)

    with tempfile.TemporaryDirectory(prefix="cfs03_trailer_v3_") as td:
        temp = Path(td)
        clips_audio = []
        for idx, seg in enumerate(source["segments"], start=1):
            start = parse_timestamp(seg["start"])
            end = parse_timestamp(seg["end"])
            dur = end - start
            wav = temp / f"dlg_{idx:02d}.wav"
            before, after = _accurate_cut_args(start, end)
            run([
                ffmpeg, "-y", *before, "-i", str(src_video), *after,
                "-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(wav),
            ])
            audio, sr = v1.read_wav(wav)
            audio = v1.resample_stereo(audio, sr, SR)
            need = int(round(dur * SR))
            audio = audio[:need] if audio.shape[0] >= need else np.pad(audio, ((0, need - audio.shape[0]), (0, 0)))
            clips_audio.append(audio)
            print(f"[v3] dialogue {idx} {dur:.3f}s", flush=True)

        n_samples = int(round(max(total_s, video_s) * SR)) + int(0.6 * SR)
        dialogue = np.zeros((n_samples, 2))
        sfx_bus = np.zeros((n_samples, 2))
        echo_bus = np.zeros((n_samples, 2))
        cursor = 0.0
        clip_starts = []
        dlg_ranges = []
        gap_ranges = []
        for i, audio in enumerate(clips_audio):
            idx = i + 1
            at = int(round(cursor * SR))
            clip_starts.append(cursor)
            dlg_ranges.append((cursor, cursor + clip_durs[i]))
            v1.mix_into(dialogue, audio, at, 1.0)
            echo_spec = echo_by.get(idx)
            if echo_spec:
                send_n = int(echo_spec["send_s"] * SR)
                tail = echo_tail_v3(audio[-send_n:], SR, float(echo_spec["wet"]))
                v1.mix_into(echo_bus, tail, at + audio.shape[0] - send_n, 1.0)
            cursor += clip_durs[i]
            if i < len(v3["transitions"]):
                spec = v3["transitions"][i]
                td_s = trans_durs[i]
                gap_ranges.append((cursor, cursor + td_s))
                for sfx_key in spec["sfx"]:
                    if sfx_key not in sfx:
                        continue
                    lead = 0.03
                    if sfx_key == "riser":
                        lead = max(0.0, 1.1 - td_s)
                    if sfx_key == "downer":
                        lead = 0.1
                    v1.mix_into(sfx_bus, sfx[sfx_key], int(round((cursor - lead) * SR)), 1.05)
                cursor += td_s
        gap_ranges.append((cursor, cursor + tail_s))

        for acc in v3["dialogue_accents"]:
            si = acc["segment_index"]
            t0 = clip_starts[si - 1] + float(acc["at_s"])
            key = {
                "reverse_swell": "reverse_swell",
                "bass_pulse": "bass_pulse",
                "boom": "boom",
                "click_impact": "click_impact",
                "impact": "impact_low",
            }[acc["type"]]
            if key in sfx:
                v1.mix_into(sfx_bus, sfx[key], int(round(t0 * SR)), 0.85)
                print(f"[v3] accent seg {si} t={t0:.2f} {acc['type']}", flush=True)

        end_at = sum(clip_durs) + sum(trans_durs)
        if "click_impact" in sfx:
            v1.mix_into(sfx_bus, sfx["click_impact"], int(round((end_at - 0.02) * SR)), 1.1)
        if "boom" in sfx:
            v1.mix_into(sfx_bus, sfx["boom"], int(round(end_at * SR)), 0.95)
        if "sub_drop" in sfx:
            v1.mix_into(sfx_bus, sfx["sub_drop"], int(round(end_at * SR)), 0.9)

        sfx_bus = peak_normalize(sfx_bus, -6.0)

        dlg_level = rms(dialogue)
        target_dlg = db_to_lin(-16.0)
        dialogue *= target_dlg / max(dlg_level, 1e-9)
        dlg_level = rms(dialogue)
        music_cut = music[:n_samples]
        if music_cut.shape[0] < n_samples:
            music_cut = np.pad(music_cut, ((0, n_samples - music_cut.shape[0]), (0, 0)))
        mus_level = rms(music_cut)
        under_db = float(mix_cfg["music_under_dialogue_db"])
        gap_db = float(mix_cfg["music_in_gaps_db"])
        intro_db = float(mix_cfg["intro_music_db"])
        under_g = (dlg_level * db_to_lin(under_db)) / max(mus_level, 1e-9)
        gap_g = (dlg_level * db_to_lin(gap_db)) / max(mus_level, 1e-9)
        intro_g = (dlg_level * db_to_lin(intro_db)) / max(mus_level, 1e-9)

        g = np.full(n_samples, gap_g)
        for a, b in dlg_ranges:
            g[int(a * SR) : int(b * SR)] = under_g
        g[: int(3.0 * SR)] = np.maximum(g[: int(3.0 * SR)], intro_g)
        g = smooth_gain(g, SR, 0.04, 0.12)

        env = v1.duck_envelope(dialogue, SR, 0.028, 0.14)
        # When speech dips inside a clip, let music rise halfway toward the gap level.
        g = g + (gap_g - g) * (1.0 - env) * 0.55

        drop_gain = np.ones(n_samples)
        for drop in v3["filter_drops"]:
            t0 = clip_starts[drop["segment_index"] - 1] + float(drop["at_s"])
            hold = float(drop["hold_s"])
            i0 = int(max(0, t0) * SR)
            i1 = int((t0 + hold) * SR)
            drop_gain[i0:i1] = 0.12
            print(f"[v3] music drop {t0:.2f}-{t0+hold:.2f}s", flush=True)
        drop_gain = smooth_gain(drop_gain, SR, 0.05, 0.08)
        g = g * drop_gain

        ducked = music_cut * g[:, None]
        mixed = dialogue * 1.08 + echo_bus * 1.25 + sfx_bus + ducked
        # Glue + compression so RMS/LUFS can sit near trailer loudness after peak limit.
        mixed = np.tanh(mixed * 1.55)
        env = np.max(np.abs(mixed), axis=1)
        thresh = 0.18
        ratio = 3.2
        cg = np.ones_like(env)
        over = env > thresh
        cg[over] = (thresh + (env[over] - thresh) / ratio) / np.maximum(env[over], 1e-9)
        cg = smooth_gain(cg, SR, 0.003, 0.05)
        mixed *= cg[:, None]
        mixed *= db_to_lin(-14.5) / max(rms(mixed), 1e-9)
        peak = float(np.max(np.abs(mixed)))
        ceiling = db_to_lin(float(mix_cfg["true_peak_dbtp"]))
        if peak > ceiling:
            mixed *= ceiling / peak

        target_n = int(round(video_s * SR))
        mixed = mixed[:target_n] if mixed.shape[0] >= target_n else np.pad(mixed, ((0, target_n - mixed.shape[0]), (0, 0)))
        ducked_save = ducked[:target_n] if ducked.shape[0] >= target_n else ducked
        v1.write_wav(ASSETS / "cfs03_trailer_v3_music_stem.wav", ducked_save[: min(len(ducked_save), target_n)])

        mix_wav = temp / "mix_v3.wav"
        v1.write_wav(mix_wav, mixed)
        mix_lim = temp / "mix_v3_tp.wav"
        # Oversampled limiter so AAC true-peak stays under -1 dBTP without flattening the mix.
        run([
            ffmpeg, "-y", "-i", str(mix_wav),
            "-af", "aresample=192000,alimiter=limit=0.5623:attack=1:release=50:level=false,aresample=48000",
            str(mix_lim),
        ])
        OUT_MP4.parent.mkdir(parents=True, exist_ok=True)
        run([
            ffmpeg, "-y",
            "-i", str(V1_MP4),
            "-i", str(mix_lim),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(OUT_MP4),
        ])

        # stem levels pre-loudnorm for the report
        def region(x, ranges):
            parts = []
            for a, b in ranges:
                parts.append(x[int(a * SR): int(min(b * SR, len(x)))])
            return np.concatenate(parts) if parts else x[:1]
        print(
            f"[v3] music_during_dlg={20*math.log10(rms(region(ducked, dlg_ranges))+1e-12):.2f} dBFS "
            f"music_gaps={20*math.log10(rms(region(ducked, gap_ranges))+1e-12):.2f} dBFS "
            f"dlg={20*math.log10(dlg_level+1e-12):.2f} dBFS",
            flush=True,
        )

    if v1.sha256_file(ORIGINAL_MP4) != h_sum:
        raise RuntimeError("Summary changed")
    if v1.sha256_file(V1_MP4) != h_v1:
        raise RuntimeError("V1 changed")
    if v1.sha256_file(V2_MP4) != h_v2:
        raise RuntimeError("V2 changed")
    print(f"[v3] wrote {OUT_MP4} duration={v1.probe_duration(ffmpeg, OUT_MP4):.3f}s", flush=True)


if __name__ == "__main__":
    main()
