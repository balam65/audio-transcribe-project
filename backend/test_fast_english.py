import sys
import os
import json
import httpx
from pathlib import Path

# Set up backend import
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config import config
from services.transcription import TranscriptionService, _is_hallucination_text, _estimate_cloud_confidence

print("Initializing fast English and Zoom stream tests...")
config.validate()

service = TranscriptionService()
service.initialize()

# Test cases representing fast English speech (10 to 30 words in 4-second chunks)
test_cases = [
    {
        "input": "Alright guys let's review the final UI designs and ensure there are no heavy effects or red glow because it makes the layout hard to read.",
        "duration": 4.0,
        "desc": "Fast English (27 words in 4 seconds)"
    },
    {
        "input": "However, it takes too much time to build this model manually so we need a cleaner automation pipeline.",
        "duration": 4.0,
        "desc": "Normal-to-fast English (19 words in 4 seconds)"
    },
    {
        "input": "Please review the current page carefully and avoid unnecessary heavy red glow effects.",
        "duration": 4.0,
        "desc": "Short sentence (12 words in 4 seconds)"
    }
]

print("\n--- RUNNING FAST ENGLISH VALIDATION ---")
for i, tc in enumerate(test_cases, 1):
    text = tc["input"]
    duration = tc["duration"]
    desc = tc["desc"]
    words_count = len(text.split())
    wps = words_count / duration
    
    print(f"\n[Test #{i}] {desc}")
    print(f"  Input: '{text}'")
    print(f"  Word count: {words_count} | Words per second: {wps:.2f}")
    
    # 1. Hallucination check
    is_hallucination = _is_hallucination_text(text)
    print(f"  Is flagged as hallucination/noise: {is_hallucination}")
    
    # 2. Confidence score check
    est_conf = _estimate_cloud_confidence(text, duration=duration)
    print(f"  Estimated Confidence: {est_conf:.3f} (Threshold is {config.CONFIDENCE_THRESHOLD})")
    
    # 3. Live Normalization / Translation Test
    print("  Sending to OpenRouter for live normalization...")
    try:
        normalized_text, should_drop = service.normalize_live_segment(
            text=text,
            duration=duration,
            source_type="live",
            confidence=est_conf
        )
        print(f"  Normalized Result: '{normalized_text}' (Should Drop: {should_drop})")
    except Exception as e:
        print(f"  Error calling normalization service: {e}")
    
print("\n--- ALL TESTS COMPLETED ---")
