"""One-off Virtual Director POC render. Does not touch the CFS renderer."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "inbox" / "03.mp4"
OUT = ROOT / "data" / "director_tests"
WORK = OUT / "_work"
WORK.mkdir(parents=True, exist_ok=True)
MEZZ = WORK / "cfs03_3420_5min_mezz.mp4"
STATIC = OUT / "CFS03_30-40_5min_static.mp4"
DIRECTED = OUT / "CFS03_30-40_5min_virtual_director.mp4"
FFMPEG = "ffmpeg"

def wide_from(src: str, tag: str) -> str:
    return (
        f"[{src}]split=3[{tag}a][{tag}b][{tag}c];"
        f"[{tag}a]crop=896:504:972:24,scale=1080:608:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad=1080:608:(ow-iw)/2:(oh-ih)/2:color=black[{tag}top];"
        f"[{tag}b]crop=896:504:512:552,scale=1080:608:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad=1080:608:(ow-iw)/2:(oh-ih)/2:color=black[{tag}mid];"
        f"[{tag}c]crop=896:504:52:24,scale=1080:608:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad=1080:608:(ow-iw)/2:(oh-ih)/2:color=black[{tag}bot];"
        f"[{tag}top][{tag}mid][{tag}bot]vstack=inputs=3,pad=1080:1920:0:48:color=black,setsar=1,fps=30"
    )

WIDE = wide_from("0:v", "w")

def portrait(box: str) -> str:
    return (
        f"crop={box},scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30"
    )

# (start, end, camera) relative to 00:34:20
SHOTS = [
    (0.000, 6.400, "wide"),
    (6.400, 50.620, "speaker_c"),
    (50.620, 74.160, "speaker_a"),
    (74.160, 98.240, "speaker_c"),
    (98.240, 157.720, "wide"),
    (157.720, 238.080, "speaker_a"),
    (238.080, 247.120, "wide"),
    (247.120, 300.000, "speaker_a"),
]


def run(args: list[str]) -> None:
    print("RUN", " ".join(args[:8]), "...", flush=True)
    subprocess.run(args, check=True)


def main() -> None:
    if not MEZZ.exists():
        run([
            FFMPEG, "-y", "-ss", "00:34:20.000", "-i", str(SRC), "-t", "300",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(MEZZ),
        ])
    run([
        FFMPEG, "-y", "-i", str(MEZZ),
        "-filter_complex", f"{WIDE}[v]",
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(STATIC),
    ])
    parts = []
    chains = ["[0:v]split=8" + "".join(f"[s{i}]" for i in range(8))]
    for i, (a, b, cam) in enumerate(SHOTS):
        if cam == "wide":
            body = wide_from(f"s{i}", f"g{i}")
            chains.append(f"{body},trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        else:
            box = "284:504:386:24" if cam == "speaker_a" else "296:528:878:552"
            chains.append(
                f"[s{i}]{portrait(box)},trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]"
            )
        parts.append(f"[v{i}]")
    chains.append("".join(parts) + f"concat=n={len(SHOTS)}:v=1:a=0[v]")
    video_only = WORK / "directed_video.mp4"
    run([
        FFMPEG, "-y", "-i", str(MEZZ),
        "-filter_complex", ";".join(chains),
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-movflags", "+faststart", str(video_only),
    ])
    run([
        FFMPEG, "-y", "-i", str(video_only), "-i", str(STATIC),
        "-map", "0:v", "-map", "1:a", "-c", "copy",
        "-shortest", "-movflags", "+faststart", str(DIRECTED),
    ])
    print("done", STATIC, DIRECTED)


if __name__ == "__main__":
    main()
