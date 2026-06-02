"""
Database models and operations for the Meeting Transcription System.
Uses SQLite with aiosqlite for async access.
"""

import json
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

try:
    from ..config import config
except ImportError:
    from config import config


# SQL schema for the meetings database
SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    status TEXT DEFAULT 'recording',
    audio_sources TEXT DEFAULT '[]',
    transcript_raw TEXT DEFAULT '',
    transcript_segments TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    key_points TEXT DEFAULT '[]',
    decisions TEXT DEFAULT '[]',
    action_items TEXT DEFAULT '[]',
    open_questions TEXT DEFAULT '[]',
    speaker_count INTEGER DEFAULT 0,
    language_detected TEXT DEFAULT '',
    word_count INTEGER DEFAULT 0,
    unclear_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    speaker TEXT DEFAULT '',
    text TEXT NOT NULL,
    confidence REAL DEFAULT 0.0,
    language TEXT DEFAULT 'en',
    is_unclear INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_segments_meeting ON transcript_segments(meeting_id);
CREATE INDEX IF NOT EXISTS idx_segments_time ON transcript_segments(start_time);
"""


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    db_path = config.get_db_path()
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    print(f"  💾 Database initialized at {db_path}")


async def get_db():
    """Get an async database connection."""
    db_path = config.get_db_path()
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    return db


async def create_meeting(title: str, audio_sources: list) -> dict:
    """Create a new meeting record."""
    meeting_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO meetings (id, title, created_at, audio_sources)
               VALUES (?, ?, ?, ?)""",
            (meeting_id, title, now, json.dumps(audio_sources)),
        )
        await db.commit()
        return {
            "id": meeting_id,
            "title": title,
            "created_at": now,
            "status": "recording",
            "audio_sources": audio_sources,
        }
    finally:
        await db.close()


async def add_segment(
    meeting_id: str,
    segment_index: int,
    start_time: float,
    end_time: float,
    text: str,
    speaker: str = "",
    confidence: float = 0.0,
    language: str = "en",
    is_unclear: bool = False,
) -> dict:
    """Add a transcript segment to the database."""
    now = datetime.utcnow().isoformat()

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO transcript_segments
               (meeting_id, segment_index, start_time, end_time, speaker, text,
                confidence, language, is_unclear, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meeting_id,
                segment_index,
                start_time,
                end_time,
                speaker,
                text,
                confidence,
                language,
                1 if is_unclear else 0,
                now,
            ),
        )
        await db.commit()
        return {
            "segment_index": segment_index,
            "start_time": start_time,
            "end_time": end_time,
            "speaker": speaker,
            "text": text,
            "confidence": confidence,
            "is_unclear": is_unclear,
        }
    finally:
        await db.close()


async def end_meeting(
    meeting_id: str,
    transcript_raw: str,
    transcript_segments: list,
    summary: str = "",
    key_points: list = None,
    decisions: list = None,
    action_items: list = None,
    open_questions: list = None,
    speaker_count: int = 0,
    language_detected: str = "",
    word_count: int = 0,
    unclear_count: int = 0,
) -> dict:
    """Update meeting record when transcription ends."""
    now = datetime.utcnow().isoformat()

    db = await get_db()
    try:
        # Calculate duration
        row = await db.execute_fetchall(
            "SELECT created_at FROM meetings WHERE id = ?", (meeting_id,)
        )
        if row:
            created = datetime.fromisoformat(row[0][0])
            ended = datetime.fromisoformat(now)
            duration = (ended - created).total_seconds()
        else:
            duration = 0

        await db.execute(
            """UPDATE meetings SET
               ended_at = ?, duration_seconds = ?, status = 'completed',
               transcript_raw = ?, transcript_segments = ?,
               summary = ?, key_points = ?, decisions = ?,
               action_items = ?, open_questions = ?,
               speaker_count = ?, language_detected = ?,
               word_count = ?, unclear_count = ?
               WHERE id = ?""",
            (
                now,
                duration,
                transcript_raw,
                json.dumps(transcript_segments),
                summary,
                json.dumps(key_points or []),
                json.dumps(decisions or []),
                json.dumps(action_items or []),
                json.dumps(open_questions or []),
                speaker_count,
                language_detected,
                word_count,
                unclear_count,
                meeting_id,
            ),
        )
        await db.commit()
        return {"id": meeting_id, "status": "completed", "duration": duration}
    finally:
        await db.close()


async def get_meeting(meeting_id: str) -> Optional[dict]:
    """Get a meeting by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
        row = await cursor.fetchone()
        if row:
            return _row_to_meeting(row)
        return None
    finally:
        await db.close()


async def get_all_meetings() -> list:
    """Get all meetings ordered by creation date."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM meetings ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [_row_to_meeting(row) for row in rows]
    finally:
        await db.close()


async def get_meeting_segments(meeting_id: str) -> list:
    """Get all transcript segments for a meeting."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM transcript_segments
               WHERE meeting_id = ? ORDER BY segment_index""",
            (meeting_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def delete_meeting(meeting_id: str) -> bool:
    """Delete a meeting and its segments."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,)
        )
        cursor = await db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


def _row_to_meeting(row) -> dict:
    """Convert a database row to a meeting dict."""
    d = dict(row)
    # Parse JSON fields
    for field in [
        "audio_sources",
        "transcript_segments",
        "key_points",
        "decisions",
        "action_items",
        "open_questions",
    ]:
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d
