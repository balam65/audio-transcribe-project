import sys
import os
import subprocess
from pathlib import Path

# Set up backend import
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config import config
from services.audio_capture import (
    list_audio_devices,
    find_monitor_device,
    get_audio_debug_snapshot
)

print("Probing system audio state and Zoom integration...")

# Probing PipeWire ports
try:
    pw_output = subprocess.run(["pw-link", "-o"], capture_output=True, text=True)
    ports = pw_output.stdout.splitlines()
    print(f"Total PipeWire Output Ports detected: {len(ports)}")
except Exception as e:
    ports = []
    print(f"Error checking PipeWire: {e}")

print("\n--- CHECKING DEVICE CLASSIFICATIONS ---")
devices = list_audio_devices()
print(f"Detected {len(devices)} input devices:")
for dev in devices:
    default_indicator = " [DEFAULT]" if dev.get("is_default_input") else ""
    monitor_indicator = " (System Audio Sink)" if dev.get("is_monitor") else " (Microphone)"
    print(f" - Index {dev['index']}: '{dev['name']}'{default_indicator}{monitor_indicator}")

print("\n--- SINK MONITOR DETECTION ---")
monitor = find_monitor_device()
if monitor:
    print(f"✅ Found System Audio Monitor: Index {monitor['index']} - '{monitor['name']}'")
    print("  This device captures all sound playing through your system (speakers, headphones, and meetings).")
else:
    print("❌ No system monitor device found. Checking fallbacks...")

print("\n--- ZOOM & PIPEWIRE ROUTING DIAGNOSTIC ---")
snapshot = get_audio_debug_snapshot()
meeting_streams = snapshot.get("meeting_streams", [])
print(f"Active Meeting Streams: {meeting_streams}")

if any("zoom" in s.lower() for s in meeting_streams):
    print("✅ Zoom VoiceEngine is actively streaming! Direct coupling is armed.")
else:
    print("ℹ️ No active direct Zoom output stream detected at this instant.")
    print("👉 Fallback: Using Active System Sink Monitor (captures all Zoom meeting audio playing on your speakers/headphones).")

print(f"Capture Target: {snapshot.get('capture_target')}")
target_ports = snapshot.get("target_ports", {})
print(f"Target Ports to Link: Left='{target_ports.get('left')}', Right='{target_ports.get('right')}'")

print("\n--- DIAGNOSTICS COMPLETED ---")
