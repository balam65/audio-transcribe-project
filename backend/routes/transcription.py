"""
Transcription WebSocket & HTTP routes.
Handles real-time transcription streaming and session management.
"""

import asyncio
import difflib
import json
import logging
import os
import threading
import queue
import tempfile
from typing import Optional

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from config import config
from services.audio_capture import (
    list_audio_devices,
    find_monitor_device,
    find_default_mic,
    CombinedAudioCapture,
    get_audio_debug_snapshot,
)
from services.transcription import TranscriptionService, TranscriptSegment
from services.speaker_detect import SpeakerDetector
from services.post_process import (
    clean_transcript_text,
    build_full_transcript,
    count_unclear_segments,
    get_word_count,
)
from services.summary import generate_summary
from models.database import create_meeting, add_segment, end_meeting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/transcription", tags=["transcription"])

# Global state for the active transcription session
_active_session = None


class TranscriptionSession:
    """Manages an active transcription session."""

    def __init__(self, meeting_id: str, meeting_title: str):
        self.meeting_id = meeting_id
        self.meeting_title = meeting_title
        self.segments: list[dict] = []
        self.segment_index = 0
        self.is_running = False
        self.websocket: Optional[WebSocket] = None

        self.audio_capture = CombinedAudioCapture()
        self.transcription = TranscriptionService()
        self.speaker_detector = SpeakerDetector()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._speaker_labels = {"system": "Meeting audio", "microphone": "Your mic"}

        # Cross-chunk deduplication ring buffer (catches Whisper repeating itself)
        self._recent_texts: list[tuple[str, float]] = []  # (normalized_text, start_time)
        self._recent_max = 8

    async def start(
        self,
        websocket: WebSocket,
        system_device: Optional[int],
        mic_device: Optional[int],
    ):
        """Start the transcription session."""
        self.websocket = websocket
        self.is_running = True
        self._loop = asyncio.get_event_loop()

        # Initialize transcription engine
        self.transcription.initialize()
        await self._send_status(
            f"Transcription provider ready: {self.transcription.engine_type}"
        )

        # Set up audio capture
        sources = self.audio_capture.setup(
            system_device_index=system_device,
            mic_device_index=mic_device,
        )

        await self._send_status(f"Capturing from: {', '.join(sources)}")

        # Start the queue worker thread
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            name="TranscriptionWorker",
            daemon=True
        )
        self._worker_thread.start()

        # Start audio capture with callback
        self.audio_capture.start(callback=self._on_audio_chunk)

        await self._send_status("Transcription started. Listening...")

    def _on_audio_chunk(self, audio_data: np.ndarray, offset: float, source_type: str):
        """Called from the audio capture thread for each chunk."""
        if not self.is_running:
            return
        # Put the chunk in the queue immediately (non-blocking)
        self._queue.put((audio_data, offset, source_type))

    def _process_queue(self):
        """Processes chunks from the queue in a background worker thread."""
        logger.info("Transcription queue processing worker started.")
        while self.is_running or not self._queue.empty():
            try:
                # Use a small timeout so the loop can check self.is_running periodically
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            audio_data, offset, source_type = item
            try:
                # Transcribe the chunk (blocking call in this separate worker thread)
                segments = self.transcription.transcribe(audio_data, time_offset=offset)

                for seg in segments:
                    seg.speaker = self._speaker_labels.get(source_type, "Speaker 1")

                    # Clean the text
                    seg.text = clean_transcript_text(seg.text)

                    if not seg.text:
                        continue

                    seg.text, should_drop = self.transcription.normalize_live_segment(
                        seg.text,
                        duration=max(seg.end_time - seg.start_time, 0.1),
                        source_type=source_type,
                        confidence=seg.confidence,
                    )
                    if should_drop or not seg.text:
                        continue

                    seg.text = clean_transcript_text(seg.text)
                    seg.is_unclear = seg.is_unclear or self._should_mark_unclear(seg, source_type)

                    if self._should_drop_as_duplicate(seg, source_type):
                        continue

                    # Cross-chunk deduplication: catch Whisper repeating itself
                    if self._is_cross_chunk_repeat(seg.text, seg.start_time):
                        continue

                    # Build segment dict
                    seg_dict = seg.to_dict()
                    seg_dict["segment_index"] = self.segment_index
                    seg_dict["source_type"] = source_type
                    self.segments.append(seg_dict)
                    self.segment_index += 1

                    # Send to WebSocket asynchronously
                    if self._loop and self.websocket:
                        asyncio.run_coroutine_threadsafe(
                            self._send_segment(seg_dict),
                            self._loop,
                        )

                    # Save to database asynchronously
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(
                            add_segment(
                                meeting_id=self.meeting_id,
                                segment_index=seg_dict["segment_index"],
                                start_time=seg.start_time,
                                end_time=seg.end_time,
                                text=seg.text,
                                speaker=seg.speaker,
                                confidence=seg.confidence,
                                language=seg.language,
                                is_unclear=seg.is_unclear,
                            ),
                            self._loop,
                        )
            except Exception as e:
                logger.error(f"Error processing queue chunk: {e}")
            finally:
                self._queue.task_done()
        logger.info("Transcription queue processing worker stopped.")

    def _should_mark_unclear(self, seg: TranscriptSegment, source_type: str) -> bool:
        """Mark weak short segments as unclear even when the provider did not."""
        text = (seg.text or "").strip()
        if not text:
            return True
        if seg.confidence < 0.38:
            return True
        if source_type == "microphone" and seg.confidence < 0.52 and len(text.split()) <= 2:
            return True
        return seg.is_unclear

    def _should_drop_as_duplicate(self, seg: TranscriptSegment, source_type: str) -> bool:
        """Drop near-duplicate segments across lanes in the same time window."""
        text = self._normalize_compare_text(seg.text)
        if not text:
            return True

        for existing in reversed(self.segments[-8:]):
            if abs(float(existing.get("start_time", 0.0)) - seg.start_time) > 1.2:
                continue

            existing_source = existing.get("source_type", "")
            if existing_source == source_type:
                continue

            existing_text = self._normalize_compare_text(existing.get("text", ""))
            if not existing_text:
                continue

            similarity = difflib.SequenceMatcher(None, text, existing_text).ratio()
            token_overlap = self._token_overlap_ratio(text, existing_text)

            if similarity >= 0.86 or token_overlap >= 0.82:
                # Prefer the meeting lane when both lanes say essentially the same thing.
                if source_type == "microphone":
                    return True
                if existing_source == "microphone":
                    existing["text"] = seg.text
                    existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), seg.confidence)
                    existing["speaker"] = seg.speaker
                    existing["is_unclear"] = seg.is_unclear
                    return True

        if source_type == "microphone" and seg.confidence < 0.5 and len(text.split()) <= 2:
            return True

        return False

    def _is_cross_chunk_repeat(self, text: str, start_time: float) -> bool:
        """Detect when Whisper repeats the same phrase across consecutive chunks.

        This is the most common hallucination pattern with Bluetooth audio and
        Zoom meeting background noise — the model latches onto a phrase and
        emits it identically in every subsequent chunk.
        """
        normalized = self._normalize_compare_text(text)
        if not normalized or len(normalized.split()) < 2:
            return False  # Too short to compare meaningfully

        for recent_text, recent_time in self._recent_texts:
            # Only compare within a reasonable time window
            time_gap = abs(start_time - recent_time)
            if time_gap > 16.0:
                continue

            # Check exact match
            if normalized == recent_text:
                return True

            # Check high similarity
            similarity = difflib.SequenceMatcher(None, normalized, recent_text).ratio()
            if similarity > 0.85:
                return True

        # Add to ring buffer
        self._recent_texts.append((normalized, start_time))
        if len(self._recent_texts) > self._recent_max:
            self._recent_texts.pop(0)

        return False

    def _normalize_compare_text(self, text: str) -> str:
        """Normalize transcript text for duplicate comparison."""
        return " ".join(
            "".join(char.lower() if char.isalnum() or char.isspace() else " " for char in str(text or "")).split()
        )

    def _token_overlap_ratio(self, left: str, right: str) -> float:
        """Measure token overlap between two normalized transcript strings."""
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))

    async def stop(self) -> dict:
        """Stop the transcription session and generate summary."""
        self.is_running = False
        self.audio_capture.stop()

        # Wait for the queue worker to finish processing final chunks
        if self._worker_thread:
            logger.info("Waiting for queue worker to finish...")
            # Run in executor to not block the main async event loop
            await asyncio.get_event_loop().run_in_executor(
                None, self._worker_thread.join, 5.0
            )

        await self._send_status("Transcription stopped. Generating summary...")

        # Build full transcript
        transcript = build_full_transcript(self.segments)
        word_count = get_word_count(self.segments)
        unclear_count = count_unclear_segments(self.segments)
        speaker_count = len({segment.get("speaker") for segment in self.segments if segment.get("speaker")})

        # Generate summary
        summary_data = generate_summary(transcript, self.meeting_title)

        # Save to database
        result = await end_meeting(
            meeting_id=self.meeting_id,
            transcript_raw=transcript,
            transcript_segments=self.segments,
            summary=summary_data.get("summary", ""),
            key_points=summary_data.get("key_points", []),
            decisions=summary_data.get("decisions", []),
            action_items=summary_data.get("action_items", []),
            open_questions=summary_data.get("open_questions", []),
            speaker_count=speaker_count,
            word_count=word_count,
            unclear_count=unclear_count,
        )

        # Send summary to client
        await self._send_message({
            "type": "summary",
            "data": {
                "summary": summary_data,
                "stats": {
                    "word_count": word_count,
                    "unclear_count": unclear_count,
                    "speaker_count": speaker_count,
                    "segment_count": len(self.segments),
                },
            },
        })

        await self._send_status("Meeting transcription complete!")
        return result

    async def _send_segment(self, segment: dict):
        """Send a transcript segment to the WebSocket client."""
        try:
            if self.websocket:
                await self.websocket.send_json({
                    "type": "segment",
                    "data": segment,
                })
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")

    async def _send_status(self, message: str):
        """Send a status message to the WebSocket client."""
        try:
            if self.websocket:
                await self.websocket.send_json({
                    "type": "status",
                    "message": message,
                })
        except Exception:
            pass

    async def _send_message(self, message: dict):
        """Send a generic message to the WebSocket client."""
        try:
            if self.websocket:
                await self.websocket.send_json(message)
        except Exception:
            pass


# --- HTTP Endpoints ---

class StartRequest(BaseModel):
    title: str = "Untitled Meeting"
    system_audio: bool = True
    mic_audio: bool = False
    system_device_index: Optional[int] = None
    mic_device_index: Optional[int] = None


@router.get("/devices")
async def get_audio_devices():
    """List available audio input devices."""
    devices = list_audio_devices()
    monitor = next((device for device in devices if device.get("is_monitor")), None)
    mic = next((device for device in devices if device.get("is_default_input")), None)
    if mic is None:
        mic = next((device for device in devices if not device.get("is_monitor")), None)
    snapshot = get_audio_debug_snapshot()
    return {
        "devices": devices,
        "default_monitor": monitor,
        "default_mic": mic,
        "connected_bluetooth_devices": snapshot.get("connected_bluetooth_devices", []),
        "bluetooth_devices": snapshot.get("bluetooth_devices", []),
        "default_source": snapshot.get("default_source"),
    }


@router.get("/status")
async def get_status():
    """Get current transcription session status."""
    global _active_session
    if _active_session and _active_session.is_running:
        return {
            "active": True,
            "meeting_id": _active_session.meeting_id,
            "meeting_title": _active_session.meeting_title,
            "segments_count": len(_active_session.segments),
        }
    return {"active": False}


@router.get("/audio-debug")
async def get_audio_debug():
    """Return current audio routing details for UI diagnostics."""
    global _active_session
    if _active_session and _active_session.is_running:
        snapshot = _active_session.audio_capture.get_debug_snapshot()
        snapshot["recording"] = True
        snapshot["meeting_id"] = _active_session.meeting_id
        snapshot["meeting_title"] = _active_session.meeting_title
        return snapshot

    snapshot = get_audio_debug_snapshot()
    snapshot["recording"] = False
    snapshot["meeting_id"] = None
    snapshot["meeting_title"] = None
    return snapshot


@router.post("/file")
async def transcribe_audio_file(
    file: UploadFile = File(...),
    title: str = Form("Uploaded Audio"),
):
    """Transcribe an uploaded audio file and save it as a meeting."""
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            temp_file.write(await file.read())

        meeting_title = title.strip() or (file.filename or "Uploaded Audio")
        meeting = await create_meeting(meeting_title, ["uploaded-file"])

        service = TranscriptionService()
        service.initialize()
        speaker_detector = SpeakerDetector()
        segments = service.transcribe_file(temp_path)

        cleaned_segments = []
        for seg in segments:
            seg.speaker = seg.speaker or "Speaker 1"
            seg.text = clean_transcript_text(seg.text)
            if not seg.text:
                continue
            seg.is_unclear = seg.is_unclear or seg.confidence < max(config.CONFIDENCE_THRESHOLD, 0.58)

            seg_dict = seg.to_dict()
            seg_dict["segment_index"] = len(cleaned_segments)
            cleaned_segments.append(seg_dict)

            await add_segment(
                meeting_id=meeting["id"],
                segment_index=seg_dict["segment_index"],
                start_time=seg.start_time,
                end_time=seg.end_time,
                text=seg.text,
                speaker=seg.speaker,
                confidence=seg.confidence,
                language=seg.language,
                is_unclear=seg.is_unclear,
            )

        transcript = build_full_transcript(cleaned_segments)
        word_count = get_word_count(cleaned_segments)
        unclear_count = count_unclear_segments(cleaned_segments)
        summary_data = generate_summary(transcript, meeting_title)

        await end_meeting(
            meeting_id=meeting["id"],
            transcript_raw=transcript,
            transcript_segments=cleaned_segments,
            summary=summary_data.get("summary", ""),
            key_points=summary_data.get("key_points", []),
            decisions=summary_data.get("decisions", []),
            action_items=summary_data.get("action_items", []),
            open_questions=summary_data.get("open_questions", []),
            speaker_count=max(1, speaker_detector.speaker_count),
            word_count=word_count,
            unclear_count=unclear_count,
        )

        return {
            "meeting_id": meeting["id"],
            "title": meeting_title,
            "segments": cleaned_segments,
            "summary": summary_data,
            "stats": {
                "word_count": word_count,
                "unclear_count": unclear_count,
                "speaker_count": max(1, speaker_detector.speaker_count),
                "segment_count": len(cleaned_segments),
            },
        }
    except Exception as e:
        logger.error(f"File transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to transcribe file: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# --- WebSocket Endpoint ---

@router.websocket("/ws")
async def transcription_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time transcription.

    Client sends:
    - {"action": "start", "title": "...", "system_audio": true, "mic_audio": false, ...}
    - {"action": "stop"}

    Server sends:
    - {"type": "segment", "data": {...}}  — real-time transcript segments
    - {"type": "status", "message": "..."}  — status updates
    - {"type": "summary", "data": {...}}  — final summary
    - {"type": "error", "message": "..."}  — errors
    """
    global _active_session
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "")

            if action == "start":
                if _active_session and _active_session.is_running:
                    await websocket.send_json({
                        "type": "error",
                        "message": "A session is already active. Stop it first.",
                    })
                    continue

                title = data.get("title", "Untitled Meeting")
                system_audio = data.get("system_audio", True)
                mic_audio = data.get("mic_audio", False)

                # Find devices
                system_device = data.get("system_device_index")
                mic_device = data.get("mic_device_index")

                if system_audio and system_device is None:
                    monitor = find_monitor_device()
                    if monitor:
                        system_device = monitor["index"]
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": "No system audio monitor device found. Install PulseAudio/PipeWire.",
                        })
                        continue

                if mic_audio and mic_device is None:
                    mic = find_default_mic()
                    if mic:
                        mic_device = mic["index"]

                # Create meeting in database
                sources = []
                if system_audio:
                    sources.append("system")
                if mic_audio:
                    sources.append("microphone")

                meeting = await create_meeting(title, sources)

                await websocket.send_json({
                    "type": "session_started",
                    "data": {
                        "meeting_id": meeting["id"],
                        "title": meeting["title"],
                    },
                })

                # Create and start session
                _active_session = TranscriptionSession(
                    meeting_id=meeting["id"],
                    meeting_title=title,
                )

                try:
                    await _active_session.start(
                        websocket=websocket,
                        system_device=system_device if system_audio else None,
                        mic_device=mic_device if mic_audio else None,
                    )
                except Exception as exc:
                    logger.error("Could not start transcription session: %s", exc)
                    _active_session = None
                    await websocket.send_json({
                        "type": "error",
                        "message": str(exc),
                    })

            elif action == "stop":
                if _active_session and _active_session.is_running:
                    await _active_session.stop()
                    _active_session = None
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session to stop.",
                    })

    except WebSocketDisconnect:
        if _active_session and _active_session.is_running:
            await _active_session.stop()
            _active_session = None
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if _active_session and _active_session.is_running:
            await _active_session.stop()
            _active_session = None
