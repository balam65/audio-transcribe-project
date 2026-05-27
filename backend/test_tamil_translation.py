import sys
import os
import json
import httpx
from pathlib import Path

# Set up backend import
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config import config
from services.transcription import TranscriptionService, _is_hallucination_text, _estimate_cloud_confidence

print("Initializing test...")
config.validate()

service = TranscriptionService()
service.initialize()

test_cases = [
    {
        "input": "வணக்கம், எப்படி இருக்கிறீர்கள்?",
        "desc": "Tamil script (Hello, how are you?)"
    },
    {
        "input": "Romba nandri friend, eppadi irukkinga?",
        "desc": "Tanglish / English Letters (Thank you friend, how are you?)"
    },
    {
        "input": "இந்த ப்ராஜெக்ட் ரொம்ப முக்கியம், சீக்கிரம் முடிக்கணும்.",
        "desc": "Tamil script (This project is very important, finish it soon)"
    }
]

print("\n--- RUNNING TRANSCRIPTION DEFENSE TESTS ---")
for i, tc in enumerate(test_cases, 1):
    text = tc["input"]
    desc = tc["desc"]
    print(f"\n[Test #{i}] {desc}")
    print(f"  Input: '{text}'")
    
    # 1. Hallucination check
    is_hallucination = _is_hallucination_text(text)
    print(f"  Is flagged as hallucination/noise: {is_hallucination}")
    
    # 2. Confidence score check
    est_conf = _estimate_cloud_confidence(text, duration=5.0)
    print(f"  Estimated Confidence: {est_conf:.3f}")
    
    # 3. Live Normalization / Translation Test
    print("  Sending to OpenRouter for translation...")
    try:
        normalized_text, should_drop = service.normalize_live_segment(
            text=text,
            duration=5.0,
            source_type="live",
            confidence=est_conf
        )
        print(f"  Result: '{normalized_text}' (Should Drop: {should_drop})")
    except Exception as e:
        print(f"  Error calling translation service: {e}")
    
print("\n--- ALL TESTS COMPLETED ---")
