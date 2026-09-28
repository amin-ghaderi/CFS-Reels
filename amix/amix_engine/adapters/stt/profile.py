"""Versioned transcription settings. These are the V1 constants, not a tuning UI."""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "amix.transcribe.v1"
ANALYSIS_WINDOW = "full_source"

# Whisper language codes. Persian is one code in this set, not a domain default.
LANGUAGES = frozenset({
    "en", "zh", "de", "es", "ru", "ko", "fr", "ja", "pt", "tr", "pl", "ca", "nl", "ar", "sv", "it",
    "id", "hi", "fi", "vi", "he", "uk", "el", "ms", "cs", "ro", "da", "hu", "ta", "no", "th", "ur",
    "hr", "bg", "lt", "la", "mi", "ml", "cy", "sk", "te", "fa", "lv", "bn", "sr", "az", "sl", "kn",
    "et", "mk", "br", "eu", "is", "hy", "ne", "mn", "bs", "kk", "sq", "sw", "gl", "mr", "pa", "si",
    "km", "sn", "yo", "so", "af", "oc", "ka", "be", "tg", "sd", "gu", "am", "yi", "lo", "uz", "fo",
    "ht", "ps", "tk", "nn", "mt", "sa", "lb", "my", "bo", "tl", "mg", "as", "tt", "haw", "ln", "ha",
    "ba", "jw", "su",
})


class InvalidLanguage(ValueError):
    code = "invalid_language"

    def __init__(self) -> None:
        super().__init__("That language code is not supported.")


class InvalidProfile(ValueError):
    code = "invalid_transcription_profile"

    def __init__(self) -> None:
        super().__init__("That transcription profile is not available.")


@dataclass(frozen=True)
class TranscriptionProfile:
    profile_id: str
    beam_size: int
    vad_filter: bool
    word_timestamps: bool
    task: str
    temperature: tuple[float, ...]


V1 = TranscriptionProfile(
    profile_id=PROFILE_ID,
    beam_size=5,
    vad_filter=True,
    word_timestamps=True,
    task="transcribe",
    temperature=(0.0,),
)


def profile_from_spec(value: object) -> TranscriptionProfile:
    if value is None:
        return V1
    if value != PROFILE_ID:
        raise InvalidProfile()
    return V1


def requested_language(value: object) -> str | None:
    """None means automatic detection. A blank or unknown code is rejected."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidLanguage()
    text = value.strip().lower()
    if not text or text not in LANGUAGES:
        raise InvalidLanguage()
    return text
