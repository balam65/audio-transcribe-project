"""
Speaker Detection Service
Detects speaker changes using energy-based heuristics and silence gaps.
Assigns speaker labels (Speaker 1, Speaker 2, etc.)
Does NOT guess or fabricate speaker names.
"""

import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class SpeakerDetector:
    """
    Lightweight speaker change detection based on audio energy patterns.
    Uses silence gaps and energy changes as heuristics.
    Never assigns real names unless explicitly provided.
    """

    def __init__(self):
        self._current_speaker = 1
        self._speaker_count = 1
        self._last_energy = 0.0
        self._silence_frames = 0
        self._energy_history = []
        self._speaker_energies = {1: []}
        self._silence_threshold = 0.01
        self._speaker_change_silence_frames = 3
        self._energy_change_ratio = 2.0

    def detect_speaker(self, audio_data: np.ndarray, text: str = "") -> str:
        """Analyze audio chunk and determine current speaker label."""
        rms = float(np.sqrt(np.mean(audio_data**2)))
        self._energy_history.append(rms)

        if rms < self._silence_threshold:
            self._silence_frames += 1
        else:
            if self._silence_frames >= self._speaker_change_silence_frames:
                if self._should_change_speaker(rms):
                    self._switch_speaker(rms)
            self._silence_frames = 0
            self._last_energy = rms
            if self._current_speaker in self._speaker_energies:
                self._speaker_energies[self._current_speaker].append(rms)

        return f"Speaker {self._current_speaker}"

    def _should_change_speaker(self, current_energy: float) -> bool:
        if self._last_energy < self._silence_threshold or len(self._energy_history) < 5:
            return False
        if self._last_energy > 0:
            ratio = current_energy / self._last_energy
            if ratio > self._energy_change_ratio or ratio < 1.0 / self._energy_change_ratio:
                return True
        return False

    def _switch_speaker(self, energy: float):
        matched = self._match_existing_speaker(energy)
        if matched and matched != self._current_speaker:
            self._current_speaker = matched
        elif not matched:
            self._speaker_count += 1
            self._current_speaker = self._speaker_count
            self._speaker_energies[self._current_speaker] = [energy]

    def _match_existing_speaker(self, energy: float) -> Optional[int]:
        best_match = None
        best_distance = float("inf")
        for speaker_id, energies in self._speaker_energies.items():
            if not energies:
                continue
            avg = float(np.mean(energies[-20:]))
            dist = abs(energy - avg)
            if dist < best_distance and dist < avg * 0.5:
                best_distance = dist
                best_match = speaker_id
        return best_match

    def reset(self):
        self._current_speaker = 1
        self._speaker_count = 1
        self._last_energy = 0.0
        self._silence_frames = 0
        self._energy_history.clear()
        self._speaker_energies = {1: []}

    @property
    def speaker_count(self) -> int:
        return self._speaker_count
