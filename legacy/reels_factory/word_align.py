from __future__ import annotations

import difflib
import re

_PUNCT = re.compile(r"^[^\w\u0600-\u06FF]+|[^\w\u0600-\u06FF]+$", re.UNICODE)


def tokenize_text(text: str) -> list[str]:
    return [tok for tok in re.split(r"\s+", str(text or "").strip()) if tok]


def _fold(token: str) -> str:
    return _PUNCT.sub("", token).replace("\u200c", "").lower()


def align_raw_words_to_clean(raw_words: list[dict], clean_text: str) -> list[dict]:
    """Keep raw timing. Attach the matching normalized token when alignment is clear."""
    raw_tokens = [str(w.get("text") or w.get("word") or "").strip() for w in raw_words]
    clean_tokens = tokenize_text(clean_text)
    raw_fold = [_fold(t) for t in raw_tokens]
    clean_fold = [_fold(t) for t in clean_tokens]
    linked = [
        {
            "text": raw_tokens[i],
            "normalized_text": None,
            "start": float(raw_words[i]["start"]),
            "end": float(raw_words[i]["end"]),
            "probability": float(raw_words[i].get("probability") or 0.0),
            "segment_id": int(raw_words[i].get("segment_id", raw_words[i].get("id", 0))),
        }
        for i in range(len(raw_words))
    ]
    if not raw_fold or not clean_fold:
        return linked
    matcher = difflib.SequenceMatcher(a=raw_fold, b=clean_fold, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for raw_i, clean_i in zip(range(i1, i2), range(j1, j2)):
            linked[raw_i]["normalized_text"] = clean_tokens[clean_i]
    return linked


def words_for_segment(word_rows: list[dict], segment_id: int) -> list[dict]:
    return [w for w in word_rows if int(w.get("segment_id", -1)) == int(segment_id)]


def snap_range_to_words(
    start: float,
    end: float,
    words: list[dict],
    *,
    pad_s: float = 0.04,
) -> tuple[float, float]:
    """Grow/shrink to whole words. Never start or end mid-token."""
    if not words or end <= start:
        return start, end
    inside = [
        w for w in words
        if float(w["end"]) >= start - pad_s and float(w["start"]) <= end + pad_s
    ]
    if not inside:
        return start, end
    return float(inside[0]["start"]), float(inside[-1]["end"])
