"""Whether the desktop webview can play a probed source directly.

Windows ships WebView2. That runtime plays an ISO-BMFF file (the ffprobe
container family ``mov,mp4,m4a,3gp,3g2,mj2``, or a plain ``mp4``/``mov``
name) when the video is H.264 and any audio is AAC. The decision uses the
probe record, not the filename and not the file size.
"""
from __future__ import annotations

from amix.amix_engine.storage.project import StoredMedia

_CONTAINERS = frozenset({"mp4", "mov", "m4v", "m4a", "3gp", "3g2", "mj2"})
_VIDEO = frozenset({"h264"})
_AUDIO = frozenset({"aac"})


def source_directly_playable(asset: StoredMedia) -> bool:
    if asset.probed_at is None or not asset.video_codec or not asset.container:
        return False
    if asset.width is None or asset.height is None or asset.duration_us is None:
        return False
    containers = {part.strip().lower() for part in asset.container.split(",") if part.strip()}
    if not containers or not containers <= _CONTAINERS:
        return False
    if asset.video_codec.strip().lower() not in _VIDEO:
        return False
    audio = (asset.audio_codec or "").strip().lower()
    return audio == "" or audio in _AUDIO
