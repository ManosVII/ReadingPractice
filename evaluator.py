import re
import difflib
import unicodedata
from typing import List


def _strip_accents(text: str) -> str:
    """Remove Greek diacritics for loose matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _normalize(text: str) -> str:
    text = text.lower()
    text = _strip_accents(text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _tokenize(text: str) -> List[str]:
    return _normalize(text).split()


def evaluate_reading(
    original: str,
    transcribed: str,
    duration_seconds: float,
    wpm_target: float = 80,
    w_acc: float = 0.60,
    w_spd: float = 0.30,
    w_pun: float = 0.10,
) -> dict:
    orig_words = _tokenize(original)
    trans_words = _tokenize(transcribed)

    if not orig_words:
        return {"error": "Κενό κείμενο"}

    # Word-level diff
    matcher = difflib.SequenceMatcher(None, orig_words, trans_words, autojunk=False)
    correct = sum(b.size for b in matcher.get_matching_blocks())

    word_accuracy = correct / len(orig_words)
    wpm = (correct / duration_seconds * 60) if duration_seconds > 0 else 0

    punct_score = _punctuation_score(original, transcribed)

    speed_norm = min(wpm / wpm_target, 1.0)
    overall = word_accuracy * w_acc + speed_norm * w_spd + punct_score * w_pun

    # Build highlighted diff for UI
    diff_tokens = _build_diff(orig_words, trans_words)

    return {
        "word_accuracy": round(word_accuracy * 100, 1),
        "wpm": round(wpm, 1),
        "punctuation_score": round(punct_score * 100, 1),
        "overall_score": round(overall * 100, 1),
        "correct_words": correct,
        "total_words": len(orig_words),
        "diff_tokens": diff_tokens,
    }


def evaluate_wpm_mode(original: str, transcribed: str, duration_seconds: float) -> dict:
    """For the 1-minute mode: only score words read, no punctuation weight."""
    orig_words = _tokenize(original)
    trans_words = _tokenize(transcribed)

    if not orig_words:
        return {"error": "Κενό κείμενο"}

    matcher = difflib.SequenceMatcher(None, orig_words, trans_words, autojunk=False)
    correct = sum(b.size for b in matcher.get_matching_blocks())
    wpm = (correct / duration_seconds * 60) if duration_seconds > 0 else 0
    accuracy = correct / len(orig_words)

    return {
        "word_accuracy": round(accuracy * 100, 1),
        "wpm": round(wpm, 1),
        "punctuation_score": 0,
        "overall_score": round(accuracy * 100, 1),
        "correct_words": correct,
        "total_words": len(orig_words),
        "diff_tokens": _build_diff(orig_words, trans_words),
    }


def _punctuation_score(original: str, transcribed: str) -> float:
    """
    Approximate punctuation adherence.
    Whisper usually adds punctuation; we check sentence-ending marks.
    """
    orig_sentences = len(re.findall(r"[.!?;]", original)) or 1
    trans_sentences = len(re.findall(r"[.!?;]", transcribed))
    ratio = trans_sentences / orig_sentences
    # Score is best when ratio is near 1
    return max(0.0, 1.0 - abs(1.0 - ratio))


def _build_diff(orig: List[str], trans: List[str]) -> list:
    """Returns list of {word, status} for UI highlighting."""
    result = []
    matcher = difflib.SequenceMatcher(None, orig, trans, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for w in orig[i1:i2]:
                result.append({"word": w, "status": "correct"})
        elif op == "replace":
            for w in orig[i1:i2]:
                result.append({"word": w, "status": "wrong"})
        elif op == "delete":
            for w in orig[i1:i2]:
                result.append({"word": w, "status": "missing"})
        elif op == "insert":
            # Extra words said — don't show in original diff
            pass
    return result
