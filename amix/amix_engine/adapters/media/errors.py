"""Failures from the media-tool boundary. These are not raw subprocess traces."""


class MediaToolMissing(RuntimeError):
    """ffmpeg or ffprobe is not available. Nothing is downloaded."""

    code = "media_tool_missing"


class ProbeFailed(RuntimeError):
    """ffprobe did not return usable metadata."""

    code = "media_probe_failed"


class ProxyFailed(RuntimeError):
    """Proxy encoding did not produce a usable file."""

    code = "media_proxy_failed"


class ProcessCancelled(RuntimeError):
    """The caller cancelled the subprocess."""
