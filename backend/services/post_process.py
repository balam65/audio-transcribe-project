"""
Post-Processing Service
Cleans transcript text while preserving accuracy.
Marks unclear sections, removes safe filler words, preserves technical terms.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Filler words that are safe to clean (only when repeated consecutively)
SAFE_FILLERS = {"um", "uh", "umm", "uhh", "hmm", "hm", "ah", "er", "erm"}


def clean_transcript_text(text: str) -> str:
    """
    Clean transcript text while preserving meaning exactly.
    
    Rules:
    - Remove repeated consecutive filler words (um, uh, etc.) but keep one
    - Fix common punctuation issues
    - Preserve technical terms exactly
    - Do NOT rewrite or paraphrase
    - Do NOT change numbers, names, or dates
    """
    if not text:
        return text

    # Don't modify [unclear] markers
    if text.startswith("[") and text.endswith("]"):
        return text

    # Remove repeated consecutive fillers (keep one instance)
    words = text.split()
    cleaned_words = []
    prev_word = ""

    for word in words:
        word_lower = word.lower().strip(".,!?")
        if word_lower in SAFE_FILLERS and word_lower == prev_word:
            continue  # Skip consecutive duplicate filler
        cleaned_words.append(word)
        prev_word = word_lower

    text = " ".join(cleaned_words)

    # Fix double spaces
    text = re.sub(r"\s+", " ", text).strip()

    # Fix common punctuation artifacts
    text = text.replace(" .", ".").replace(" ,", ",")
    text = text.replace(" ?", "?").replace(" !", "!")

    return text


def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_full_transcript(segments: list) -> str:
    """
    Build a clean, formatted full transcript from segments.
    Includes timestamps and speaker labels.
    """
    if not segments:
        return ""

    lines = []
    current_speaker = ""

    for seg in segments:
        timestamp = format_timestamp(seg.get("start_time", 0))
        speaker = seg.get("speaker", "")
        text = seg.get("text", "")

        # Clean the text
        text = clean_transcript_text(text)

        if not text:
            continue

        # Add speaker label if it changed
        if speaker and speaker != current_speaker:
            lines.append("")  # Empty line before speaker change
            lines.append(f"[{timestamp}] {speaker}:")
            current_speaker = speaker

        lines.append(f"  [{timestamp}] {text}")

    return "\n".join(lines).strip()


def count_unclear_segments(segments: list) -> int:
    """Count the number of unclear/inaudible segments."""
    return sum(1 for s in segments if s.get("is_unclear", False))


def get_word_count(segments: list) -> int:
    """Count total words in the transcript."""
    total = 0
    for seg in segments:
        text = seg.get("text", "")
        if not text.startswith("[unclear"):
            total += len(text.split())
    return total
