"""
Audio Capture Service
Handles capturing system audio (from PulseAudio monitor) and microphone input.
Converts audio into chunks suitable for streaming transcription.
"""

import asyncio
import contextlib
import logging
import os
import struct
import subprocess
import threading
import time
from typing import Callable, Optional

import numpy as np

from config import config

logger = logging.getLogger(__name__)

SYSTEM_DEVICE_HINTS = ("monitor", "pipewire", "pulse")
MEETING_STREAM_HINTS = (
    "ZOOM VoiceEngine",
    "Google Chrome",
    "Chromium",
    "firefox",
    "Slack",
    "Teams",
)
BLUETOOTH_DEVICE_HINTS = ("bluetooth", "airpods", "buds", "a2dp", "hfp", "hsp", "wf-", "wh-")
WIRED_DEVICE_HINTS = ("headset", "headphone", "earphone", "usb", "jack", "analog", "line in", "line-in")

os.environ.setdefault("JACK_NO_START_SERVER", "1")

# Try to import PyAudio — it requires system-level PortAudio
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logger.warning("PyAudio not available. Install portaudio19-dev and PyAudio.")


_DEVICE_CACHE: list[dict] = []
_DEVICE_CACHE_TS = 0.0
_DEVICE_CACHE_TTL_SECONDS = 8.0


@contextlib.contextmanager
def _suppress_audio_backend_stderr():
    """Mute noisy ALSA/JACK stderr output during PortAudio probing/opening."""
    stderr_fd = None
    saved_fd = None
    devnull_fd = None

    try:
        stderr_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        if stderr_fd is not None:
            os.dup2(stderr_fd, 2)
        if devnull_fd is not None:
            os.close(devnull_fd)
        if stderr_fd is not None:
            os.close(stderr_fd)


def list_audio_devices(force_refresh: bool = False) -> list:
    """
    List all available audio input devices.
    Returns a list of dicts with device info.
    Identifies PulseAudio monitor sources for system audio capture.
    """
    global _DEVICE_CACHE, _DEVICE_CACHE_TS

    if not PYAUDIO_AVAILABLE:
        return []

    now = time.time()
    if not force_refresh and _DEVICE_CACHE and (now - _DEVICE_CACHE_TS) < _DEVICE_CACHE_TTL_SECONDS:
        return [device.copy() for device in _DEVICE_CACHE]

    with _suppress_audio_backend_stderr():
        pa = pyaudio.PyAudio()
    devices = []
    default_source = _get_default_source_details()

    try:
        with _suppress_audio_backend_stderr():
            device_count = pa.get_device_count()
        for i in range(device_count):
            with _suppress_audio_backend_stderr():
                info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                raw_name = info["name"]
                name_lower = raw_name.lower()
                is_monitor = any(hint in name_lower for hint in SYSTEM_DEVICE_HINTS)
                display_name = raw_name
                connection_name = raw_name
                is_default_input = False

                if name_lower == "default" and default_source:
                    is_monitor = False
                    is_default_input = True
                    display_name = default_source.get("description") or "Default Input"
                    connection_name = (
                        default_source.get("description")
                        or default_source.get("node_name")
                        or raw_name
                    )

                connection = _classify_audio_connection(connection_name, is_monitor=is_monitor)
                devices.append({
                    "index": i,
                    "name": display_name,
                    "channels": info["maxInputChannels"],
                    "sample_rate": int(info["defaultSampleRate"]),
                    "is_monitor": is_monitor,
                    "type": "system" if is_monitor else "microphone",
                    "connection": connection,
                    "connection_label": connection.replace("_", " ").title(),
                    "is_default_input": is_default_input,
                })
    finally:
        pa.terminate()

    _DEVICE_CACHE = [device.copy() for device in devices]
    _DEVICE_CACHE_TS = now
    return devices


def _classify_audio_connection(device_name: str, is_monitor: bool = False) -> str:
    """Best-effort classification for how a device is connected."""
    if is_monitor:
        return "system"

    name_lower = device_name.lower()
    if "bluez" in name_lower or "nirvana" in name_lower:
        return "bluetooth"
    if any(hint in name_lower for hint in BLUETOOTH_DEVICE_HINTS):
        return "bluetooth"
    if any(hint in name_lower for hint in WIRED_DEVICE_HINTS):
        return "wired"
    return "built_in"


def find_monitor_device() -> Optional[dict]:
    """
    Find the PulseAudio monitor device for capturing system audio.
    This captures all audio playing through the speakers (meeting audio).
    """
    devices = list_audio_devices()
    monitors = [d for d in devices if d["is_monitor"]]
    if monitors:
        return monitors[0]
    
    # Robust fallback for PipeWire / PulseAudio virtual devices
    for name in ["pulse", "pipewire", "default"]:
        for d in devices:
            if name in d["name"].lower():
                fallback = d.copy()
                fallback["is_monitor"] = True
                fallback["type"] = "system"
                return fallback
                
    return None


def find_default_mic() -> Optional[dict]:
    """Find the default microphone device."""
    devices = list_audio_devices()
    default_inputs = [d for d in devices if d.get("is_default_input")]
    if default_inputs:
        return default_inputs[0]
    mics = [d for d in devices if not d["is_monitor"]]
    if mics:
        return mics[0]
    return None


def _get_device_info(pa: "pyaudio.PyAudio", device_index: int) -> dict:
    """Fetch PyAudio device info with sensible defaults."""
    info = pa.get_device_info_by_index(device_index)
    return {
        "index": device_index,
        "name": info.get("name", f"Device {device_index}"),
        "input_channels": max(1, int(info.get("maxInputChannels") or 1)),
        "sample_rate": int(info.get("defaultSampleRate") or config.SAMPLE_RATE),
    }


def _run_command(command: list[str]) -> str:
    """Run a system command and return stdout, or an empty string on failure."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except Exception:
        return ""


def _get_default_source_details() -> Optional[dict]:
    """Return metadata for the current PipeWire default input source."""
    output = _run_command(["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"])
    if not output:
        return None

    details: dict[str, str] = {}
    for line in output.splitlines():
        if "node.description" in line:
            details["description"] = line.split("=", 1)[1].strip().strip('"')
        elif "node.name" in line:
            details["node_name"] = line.split("=", 1)[1].strip().strip('"')

    return details or None


def _get_connected_bluetooth_devices() -> list[str]:
    """Return connected Bluetooth device names when available."""
    output = _run_command(["bluetoothctl", "devices", "Connected"])
    devices: list[str] = []
    for line in output.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            devices.append(parts[2])
    return devices


def _get_bluetooth_device_inventory() -> list[dict]:
    """Return paired Bluetooth devices with basic connection metadata."""
    output = _run_command(["bluetoothctl", "devices"])
    devices: list[dict] = []
    for line in output.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) != 3 or parts[0] != "Device":
            continue

        address = parts[1]
        name = parts[2]
        info = _run_command(["bluetoothctl", "info", address])
        connected = "Connected: yes" in info
        handsfree = "Handsfree" in info or "Headset" in info or "Generic Audio" in info
        devices.append({
            "address": address,
            "name": name,
            "connected": connected,
            "mic_capable": handsfree,
        })
    return devices


def _get_default_sink_node_name() -> Optional[str]:
    """Get the active PipeWire default sink node name."""
    output = _run_command(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    for line in output.splitlines():
        if "node.name" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _get_default_source_node_name() -> Optional[str]:
    """Get the active PipeWire default source node name."""
    output = _run_command(["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"])
    for line in output.splitlines():
        if "node.name" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _get_meeting_stream_ports(output_ports: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Prefer direct meeting app streams when available."""
    for hint in MEETING_STREAM_HINTS:
        left = next((port for port in output_ports if f"{hint}:output_FL" in port), None)
        right = next((port for port in output_ports if f"{hint}:output_FR" in port), None)
        if left or right:
            return left, right
        mono = next((port for port in output_ports if f"{hint}:output_MONO" in port), None)
        if mono:
            return mono, None
    return None, None


def _get_meeting_stream_names(output_ports: list[str]) -> list[str]:
    """Return visible meeting-related PipeWire output streams."""
    matches = []
    for port in output_ports:
        stream_name = port.split(":", 1)[0].strip()
        if any(hint.lower() in stream_name.lower() for hint in MEETING_STREAM_HINTS):
            if stream_name not in matches:
                matches.append(stream_name)
    return matches


def _get_monitor_ports(output_ports: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Find monitor ports for the active default sink, then fall back to any monitor ports."""
    default_sink = _get_default_sink_node_name()
    if default_sink:
        left = next((port for port in output_ports if f"{default_sink}:monitor_FL" in port), None)
        right = next((port for port in output_ports if f"{default_sink}:monitor_FR" in port), None)
        if left or right:
            return left, right
        mono = next((port for port in output_ports if f"{default_sink}:monitor_MONO" in port), None)
        if mono:
            return mono, None

    left = next((port for port in output_ports if "monitor_FL" in port), None)
    right = next((port for port in output_ports if "monitor_FR" in port), None)
    if left or right:
        return left, right

    mono = next((port for port in output_ports if "monitor_MONO" in port), None)
    return mono, None


def _describe_device_by_index(device_index: Optional[int]) -> Optional[dict]:
    """Describe a PyAudio device by index."""
    if device_index is None or not PYAUDIO_AVAILABLE:
        return None

    with _suppress_audio_backend_stderr():
        pa = pyaudio.PyAudio()
    try:
        with _suppress_audio_backend_stderr():
            info = _get_device_info(pa, device_index)
        return {
            "index": device_index,
            "name": info["name"],
            "sample_rate": info["sample_rate"],
            "channels": info["input_channels"],
        }
    except Exception:
        return None
    finally:
        pa.terminate()


def get_audio_debug_snapshot(
    selected_system_device_index: Optional[int] = None,
    selected_mic_device_index: Optional[int] = None,
    active_capture: Optional[list[dict]] = None,
) -> dict:
    """Collect a lightweight snapshot of the current Linux audio routing state."""
    output_ports = _run_command(["pw-link", "-o"]).splitlines()
    default_sink = _get_default_sink_node_name()
    default_source = _get_default_source_node_name()
    meeting_left, meeting_right = _get_meeting_stream_ports(output_ports)
    monitor_left, monitor_right = _get_monitor_ports(output_ports)
    capture_target = "sink_monitor" if (monitor_left or monitor_right) else "meeting_stream"

    return {
        "selected_system_device": _describe_device_by_index(selected_system_device_index),
        "selected_mic_device": _describe_device_by_index(selected_mic_device_index),
        "active_capture": active_capture or [],
        "default_sink": default_sink,
        "default_source": default_source,
        "connected_bluetooth_devices": _get_connected_bluetooth_devices(),
        "bluetooth_devices": _get_bluetooth_device_inventory(),
        "meeting_streams": _get_meeting_stream_names(output_ports),
        "capture_target": capture_target,
        "target_ports": {
            "left": monitor_left or meeting_left,
            "right": monitor_right or meeting_right,
        },
    }


class AudioCaptureStream:
    """
    Captures audio from a specified device in real-time chunks.
    Each chunk is a numpy array of audio samples at 16kHz mono.

    Usage:
        stream = AudioCaptureStream(device_index=0, source_type="system")
        stream.start(callback=my_callback)
        # ... later
        stream.stop()
    """

    def __init__(
        self,
        device_index: int,
        source_type: str = "system",
        chunk_duration: float = None,
    ):
        self.device_index = device_index
        self.source_type = source_type
        self.chunk_duration = chunk_duration or config.AUDIO_CHUNK_DURATION
        self.sample_rate = config.SAMPLE_RATE
        self.channels = config.CHANNELS

        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._buffer = bytearray()
        self._callback: Optional[Callable] = None
        self._chunk_size = int(self.sample_rate * self.chunk_duration)
        self._input_rate = self.sample_rate
        self._input_channels = 1
        self._device_name = f"device-{device_index}"

        # Track timing for offset calculation
        self._start_time: float = 0.0
        self._chunks_sent: int = 0

    def start(self, callback: Callable):
        """
        Start capturing audio. Calls `callback(audio_data, offset_seconds)`
        for each chunk of audio data.
        """
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError(
                "PyAudio is not installed. Run: sudo apt-get install portaudio19-dev && pip install PyAudio"
            )

        self._callback = callback
        self._running = True
        self._start_time = time.time()
        self._chunks_sent = 0
        self._buffer = bytearray()

        with _suppress_audio_backend_stderr():
            self._pa = pyaudio.PyAudio()
            device_info = _get_device_info(self._pa, self.device_index)
        self._input_rate = device_info["sample_rate"]
        self._input_channels = min(device_info["input_channels"], 2)
        self._device_name = device_info["name"]

        # Open the audio stream
        # Read at the device's native format, then downmix/resample for Whisper.
        frames_per_buffer = max(1024, int(self._input_rate * 0.064))
        with _suppress_audio_backend_stderr():
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._input_channels,
                rate=self._input_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=frames_per_buffer,
            )

        # Start capture in a background thread
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"AudioCapture-{self.source_type}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"Audio capture started: {self.source_type} ({self._device_name}, "
            f"{self._input_rate}Hz/{self._input_channels}ch)"
        )

        # For system capture on PipeWire, run auto-linker in a background thread
        if self.source_type == "system":
            threading.Thread(
                target=self._link_pipewire_ports,
                name="PipeWire-AutoLinker",
                daemon=True
            ).start()

    def _link_pipewire_ports(self):
        """Automatically link PipeWire monitor output ports to our application's input ports."""
        time.sleep(1.5)  # Wait for PyAudio stream to register with PipeWire
        try:
            output_ports = _run_command(["pw-link", "-o"]).splitlines()
            input_ports = _run_command(["pw-link", "-i"]).splitlines()

            # Look for our stream's input ports first, then fall back to the first visible pair.
            app_fl = next((p for p in input_ports if "input_FL" in p and "python" in p.lower()), None)
            app_fr = next((p for p in input_ports if "input_FR" in p and "python" in p.lower()), None)
            app_mono = next((p for p in input_ports if "input_MONO" in p and "python" in p.lower()), None)
            app_fl = app_fl or next((p for p in input_ports if "input_FL" in p), None)
            app_fr = app_fr or next((p for p in input_ports if "input_FR" in p), None)
            app_mono = app_mono or next((p for p in input_ports if "input_MONO" in p), None)

            target_fl, target_fr = _get_monitor_ports(output_ports)
            if target_fl or target_fr:
                logger.info("PipeWire auto-link: capturing active sink monitor")
            else:
                target_fl, target_fr = _get_meeting_stream_ports(output_ports)
                if target_fl or target_fr:
                    logger.info("PipeWire auto-link: falling back to direct meeting app stream")

            if target_fl and app_fl:
                logger.info(f"Auto-linking PipeWire: {target_fl} -> {app_fl}")
                subprocess.run(["pw-link", target_fl, app_fl], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif target_fl and app_mono:
                logger.info(f"Auto-linking PipeWire: {target_fl} -> {app_mono}")
                subprocess.run(["pw-link", target_fl, app_mono], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if target_fr and app_fr:
                logger.info(f"Auto-linking PipeWire: {target_fr} -> {app_fr}")
                subprocess.run(["pw-link", target_fr, app_fr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif target_fl and not target_fr and app_fr:
                logger.info(f"Auto-linking PipeWire mono source: {target_fl} -> {app_fr}")
                subprocess.run(["pw-link", target_fl, app_fr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.warning(f"Could not auto-link PipeWire ports (non-fatal): {e}")

    def _capture_loop(self):
        """Main capture loop running in a background thread."""
        frames_per_chunk = int(self._input_rate * self.chunk_duration)
        bytes_per_chunk = frames_per_chunk * 2 * self._input_channels  # int16 * channels

        while self._running:
            try:
                # Read a small buffer of audio data
                data = self._stream.read(
                    max(1024, int(self._input_rate * 0.064)),
                    exception_on_overflow=False,
                )
                self._buffer.extend(data)

                # When we have enough data for one chunk, process it
                while len(self._buffer) >= bytes_per_chunk:
                    chunk_bytes = bytes(self._buffer[:bytes_per_chunk])
                    self._buffer = self._buffer[bytes_per_chunk:]

                    audio_np = self._prepare_audio(chunk_bytes)

                    # Calculate time offset
                    offset = self._chunks_sent * self.chunk_duration
                    self._chunks_sent += 1

                    # Call the callback with audio data, offset, and source type
                    if self._callback:
                        self._callback(audio_np, offset, self.source_type)

            except Exception as e:
                if self._running:
                    logger.error(f"Audio capture error: {e}")
                    time.sleep(0.1)

    def _prepare_audio(self, chunk_bytes: bytes) -> np.ndarray:
        """Convert native device PCM into 16kHz mono float32 audio."""
        frame_width = 2 * self._input_channels
        if len(chunk_bytes) < frame_width:
            return np.zeros(0, dtype=np.float32)

        usable_bytes = len(chunk_bytes) - (len(chunk_bytes) % frame_width)
        if usable_bytes != len(chunk_bytes):
            chunk_bytes = chunk_bytes[:usable_bytes]

        audio_np = np.frombuffer(chunk_bytes, dtype=np.int16).astype(np.float32)

        if self._input_channels > 1:
            audio_np = audio_np.reshape(-1, self._input_channels).mean(axis=1)

        audio_np /= 32768.0

        if self._input_rate != self.sample_rate and len(audio_np) > 1:
            target_len = int(len(audio_np) * self.sample_rate / self._input_rate)
            source_positions = np.linspace(0, len(audio_np) - 1, num=len(audio_np), dtype=np.float32)
            target_positions = np.linspace(0, len(audio_np) - 1, num=target_len, dtype=np.float32)
            audio_np = np.interp(target_positions, source_positions, audio_np).astype(np.float32)

        return audio_np

    def stop(self):
        """Stop the audio capture."""
        self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)

        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass

        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass

        # Process any remaining audio in the buffer
        if self._buffer and self._callback:
            remaining = bytes(self._buffer)
            if len(remaining) >= 2:
                audio_np = self._prepare_audio(remaining)
                offset = self._chunks_sent * self.chunk_duration
                self._callback(audio_np, offset, self.source_type)

        logger.info(f"Audio capture stopped: {self.source_type}")

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since capture started."""
        if self._start_time:
            return time.time() - self._start_time
        return 0.0

    @property
    def debug_info(self) -> dict:
        """Return capture details for UI diagnostics."""
        return {
            "source_type": self.source_type,
            "device_index": self.device_index,
            "device_name": self._device_name,
            "input_rate": self._input_rate,
            "input_channels": self._input_channels,
        }


class CombinedAudioCapture:
    """
    Manages capturing from multiple audio sources simultaneously
    (system audio + optional microphone).
    Keeps the lanes separate for transcription and suppresses obvious mic bleed.
    """

    def __init__(self):
        self._streams: list[AudioCaptureStream] = []
        self._running = False
        self._callback: Optional[Callable] = None
        self._lock = threading.Lock()
        self._pending_chunks: dict[int, dict[str, np.ndarray]] = {}
        self._pending_received_at: dict[int, float] = {}
        self.system_device_index: Optional[int] = None
        self.mic_device_index: Optional[int] = None
        self._chunk_duration = float(config.AUDIO_CHUNK_DURATION)

    def setup(
        self,
        system_device_index: Optional[int] = None,
        mic_device_index: Optional[int] = None,
    ) -> list:
        """
        Set up audio capture sources.
        Returns list of configured sources.
        """
        sources = []
        self.system_device_index = system_device_index
        self.mic_device_index = mic_device_index

        if system_device_index is not None:
            stream = AudioCaptureStream(
                device_index=system_device_index,
                source_type="system",
            )
            self._streams.append(stream)
            sources.append("system")

        if mic_device_index is not None:
            stream = AudioCaptureStream(
                device_index=mic_device_index,
                source_type="microphone",
            )
            self._streams.append(stream)
            sources.append("microphone")

        return sources

    def start(self, callback: Callable):
        """Start all configured audio streams."""
        self._callback = callback
        self._running = True

        for stream in self._streams:
            stream.start(callback=self._on_audio_chunk)

    def _on_audio_chunk(self, audio_data: np.ndarray, offset: float, source_type: str):
        """Handle audio chunks from any source and emit clean transcription lanes."""
        if not self._callback or not self._running:
            return

        if len(self._streams) <= 1:
            self._callback(audio_data, offset, source_type)
            return

        bucket = int(round(offset / max(self._chunk_duration, 0.001)))
        to_emit: list[tuple[np.ndarray, float, str]] = []

        with self._lock:
            entry = self._pending_chunks.setdefault(bucket, {})
            entry[source_type] = audio_data
            self._pending_received_at[bucket] = time.time()

            if "system" in entry and "microphone" in entry:
                to_emit.extend(
                    self._build_transcription_lanes(
                        entry["system"],
                        entry["microphone"],
                        bucket * self._chunk_duration,
                    )
                )
                self._pending_chunks.pop(bucket, None)
                self._pending_received_at.pop(bucket, None)

            to_emit.extend(self._flush_stale_chunks_locked(current_bucket=bucket))

        for lane_audio, lane_offset, lane_type in to_emit:
            self._callback(lane_audio, lane_offset, lane_type)

    def _flush_stale_chunks_locked(self, current_bucket: int) -> list[tuple[np.ndarray, float, str]]:
        """Flush pending buckets that never received both sources."""
        cutoff_age = max(0.8, self._chunk_duration * 0.6)
        now = time.time()
        ready: list[tuple[np.ndarray, float, str]] = []

        for bucket in sorted(list(self._pending_chunks.keys())):
            if bucket >= current_bucket:
                continue
            if (now - self._pending_received_at.get(bucket, now)) < cutoff_age:
                continue

            ready.extend(
                self._resolve_pending_bucket(
                    self._pending_chunks[bucket],
                    bucket * self._chunk_duration,
                )
            )

            self._pending_chunks.pop(bucket, None)
            self._pending_received_at.pop(bucket, None)

        return ready

    def _resolve_pending_bucket(
        self,
        entry: dict[str, np.ndarray],
        offset: float,
    ) -> list[tuple[np.ndarray, float, str]]:
        """Return the best available transcription lanes for a pending time bucket."""
        system_audio = entry.get("system")
        mic_audio = entry.get("microphone")

        if system_audio is not None and mic_audio is not None:
            return self._build_transcription_lanes(system_audio, mic_audio, offset)
        if system_audio is not None:
            return [(system_audio, offset, "system")]
        if mic_audio is not None:
            return [(mic_audio, offset, "microphone")]
        return []

    def _build_transcription_lanes(
        self,
        system_audio: np.ndarray,
        mic_audio: np.ndarray,
        offset: float,
    ) -> list[tuple[np.ndarray, float, str]]:
        """Keep system and mic as separate lanes while rejecting obvious echo bleed."""
        if system_audio.size == 0 and mic_audio.size == 0:
            return []
        if system_audio.size == 0:
            return [(mic_audio, offset, "microphone")]
        if mic_audio.size == 0:
            return [(system_audio, offset, "system")]

        length = min(len(system_audio), len(mic_audio))
        if length <= 0:
            return [(system_audio, offset, "system")]

        system = np.asarray(system_audio[:length], dtype=np.float32)
        mic = np.asarray(mic_audio[:length], dtype=np.float32)

        system_rms = float(np.sqrt(np.mean(system**2))) if system.size else 0.0
        mic_rms = float(np.sqrt(np.mean(mic**2))) if mic.size else 0.0
        lanes: list[tuple[np.ndarray, float, str]] = []

        if system_rms >= config.LIVE_MIN_RMS:
            lanes.append((system, offset, "system"))
        if mic_rms < config.LIVE_MIN_RMS:
            return lanes
        if system_rms < config.LIVE_MIN_RMS:
            return lanes + [(mic, offset, "microphone")]

        correlation = self._normalized_correlation(system, mic)
        mic_clean = mic

        # Strong similarity usually means the microphone is mostly hearing the speakers.
        if correlation > 0.72:
            bleed_scale = float(np.dot(mic, system) / max(np.dot(system, system), 1e-6))
            bleed_scale = max(0.0, min(bleed_scale, 1.1))
            mic_clean = mic - (system * bleed_scale)

        mic_clean_rms = float(np.sqrt(np.mean(mic_clean**2))) if mic_clean.size else 0.0
        if correlation > 0.72 and mic_clean_rms < config.LIVE_MIN_RMS * 1.1:
            return lanes

        peak = float(np.max(np.abs(mic_clean))) if mic_clean.size else 0.0
        if peak > 0.98:
            mic_clean = mic_clean / peak * 0.98

        lanes.append((mic_clean.astype(np.float32), offset, "microphone"))
        return lanes

    def _normalized_correlation(self, left: np.ndarray, right: np.ndarray) -> float:
        """Estimate similarity between two chunks to detect bleed-through."""
        if left.size == 0 or right.size == 0:
            return 0.0

        length = min(left.size, right.size)
        left = left[:length]
        right = right[:length]

        left_norm = float(np.linalg.norm(left))
        right_norm = float(np.linalg.norm(right))
        if left_norm < 1e-6 or right_norm < 1e-6:
            return 0.0

        return float(np.dot(left, right) / (left_norm * right_norm))

    def stop(self):
        """Stop all audio streams."""
        self._running = False
        for stream in self._streams:
            stream.stop()
        self._streams.clear()

        pending_emit: list[tuple[np.ndarray, float, str]] = []
        with self._lock:
            for bucket in sorted(self._pending_chunks.keys()):
                pending_emit.extend(
                    self._resolve_pending_bucket(
                        self._pending_chunks[bucket],
                        bucket * self._chunk_duration,
                    )
                )
            self._pending_chunks.clear()
            self._pending_received_at.clear()

        if self._callback:
            for audio_data, offset, source_type in pending_emit:
                self._callback(audio_data, offset, source_type)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_debug_snapshot(self) -> dict:
        """Return the active capture plus PipeWire routing context."""
        return get_audio_debug_snapshot(
            selected_system_device_index=self.system_device_index,
            selected_mic_device_index=self.mic_device_index,
            active_capture=[stream.debug_info for stream in self._streams],
        )
