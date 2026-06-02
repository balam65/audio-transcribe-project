"""
Meeting CRUD routes.
Handles listing, viewing, and deleting meetings.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from auth import require_authenticated_request
from models.database import get_all_meetings, get_meeting, get_meeting_segments, delete_meeting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("/")
async def list_meetings(request: Request):
    """Get all meetings ordered by date."""
    require_authenticated_request(request)
    meetings = await get_all_meetings()
    return {"meetings": meetings}


@router.get("/{meeting_id}")
async def get_meeting_detail(meeting_id: str, request: Request):
    """Get a single meeting with full details."""
    require_authenticated_request(request)
    meeting = await get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    segments = await get_meeting_segments(meeting_id)
    meeting["segments"] = segments
    return meeting


@router.delete("/{meeting_id}")
async def remove_meeting(meeting_id: str, request: Request):
    """Delete a meeting and all its data."""
    require_authenticated_request(request)
    success = await delete_meeting(meeting_id)
    if not success:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"success": True, "message": "Meeting deleted"}
