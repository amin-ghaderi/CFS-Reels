"""Analysis kinds stored on runs and active pointers.

These are data values, not filenames. ``latest`` and ``v3`` are not kinds.
"""

TRANSCRIPT = "transcript"
DIARIZATION = "diarization"
PARTICIPANT_ASSIGNMENT = "participant_assignment"
TURNS = "turns"
OVERLAP = "overlap"
SHOT_PLAN = "shot_plan"
CONVERSATION_MAP = "conversation_map"

ANALYSIS_KINDS = frozenset({
    TRANSCRIPT,
    DIARIZATION,
    PARTICIPANT_ASSIGNMENT,
    TURNS,
    OVERLAP,
    SHOT_PLAN,
    CONVERSATION_MAP,
})

WORD_TEXT = "word_text"
SPEAKER_OVERRIDE = "speaker_override"

# Domain roles from the media model. Not a filename taxonomy.
MEDIA_ROLES = frozenset({"master", "proxy", "audio_extract", "export", "sidecar"})
DEFAULT_MEDIA_ROLE = "master"
WORD_PAGE_LIMIT = 400
